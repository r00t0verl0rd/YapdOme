"""Локальная интеграция DonationAlerts: OAuth, Centrifugo и очередь событий.

Только стандартная библиотека Python; секреты и токены остаются на этом компьютере.
"""
import base64
import hashlib
import json
import os
import queue
import secrets
import socket
import ssl
import struct
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from pathlib import Path


API_ROOT = "https://www.donationalerts.com/api/v1"
AUTHORIZE_URL = "https://www.donationalerts.com/oauth/authorize"
TOKEN_URL = "https://www.donationalerts.com/oauth/token"
CENTRIFUGO_HOST = "centrifugo.donationalerts.com"
CENTRIFUGO_PATH = "/connection/websocket"
SCOPES = "oauth-user-show oauth-donation-subscribe"
CONFIG_PATH = Path.home() / ".triad-dialogue" / "donationalerts.json"
_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class DonationAlertsError(RuntimeError):
    """Понятная локальная ошибка интеграции."""


def _safe_text(value, limit):
    text = str(value or "")
    return "".join(ch for ch in text if ch >= " " and ch not in
                   "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")[:limit].strip()


def _publication_envelope(message):
    """Нормализует оболочку Centrifugo v2 (result) и v3+ (push)."""
    if not isinstance(message, dict):
        return None
    push = message.get("push")
    if isinstance(push, dict):
        return push
    # DonationAlerts всё ещё использует legacy envelope: result.channel/data.
    result = message.get("result")
    if isinstance(result, dict) and result.get("channel"):
        return result
    return message


def _parse_donation_publication(message, channel):
    """Возвращает (донат, причина отказа); не сохраняет исходное сообщение."""
    push = _publication_envelope(message)
    if not isinstance(push, dict):
        return None, "входящее сообщение не является объектом"
    if push.get("channel") != channel:
        return None, "сообщение пришло не из канала донатов"
    publication = push.get("pub") or push.get("publication")
    if publication is None:
        # Legacy Centrifugo v2 wraps the publication directly in result.
        publication = push
    if not isinstance(publication, dict):
        return None, "в публикации отсутствует объект pub/publication"
    data = publication.get("data")
    if data is None:
        data = push.get("data")
    if not isinstance(data, dict):
        return None, "в публикации отсутствует объект data"
    nested = data.get("donation")
    if nested is None:
        nested = data.get("data")
    if nested is not None:
        if not isinstance(nested, dict):
            return None, "вложенное поле donation/data не является объектом"
        data = nested
    # This parser is called only for the private $alerts:donation_<user_id>
    # channel. DonationAlerts documents this channel as donation-only; some
    # live payload variants carry a different/missing resource name, so the
    # channel plus required donation fields are the reliable discriminator.
    raw_id = data.get("id")
    if raw_id is None or str(raw_id).strip() == "":
        return None, "в донате отсутствует id"
    try:
        amount = float(data.get("amount"))
    except (TypeError, ValueError):
        return None, "amount отсутствует или не является числом"
    if not (0 <= amount <= 1_000_000):
        return None, "amount вне допустимого диапазона 0–1 000 000"
    username = _safe_text(data.get("username") or data.get("donor") or "Аноним", 32)
    text = _safe_text(data.get("message") or "", 600)
    currency = _safe_text(data.get("currency") or "", 8).upper()
    return {
        "id": str(raw_id),
        "donor": username or "Аноним",
        "amount": round(amount, 2),
        "currency": currency,
        "text": text or "Спасибо за поддержку!",
        "created_at": _safe_text(data.get("created_at") or "", 32),
    }, ""


def extract_donation(message, channel):
    """Совместимый публичный интерфейс парсера: None или нормализованный донат."""
    donation, _reason = _parse_donation_publication(message, channel)
    return donation


class _WebSocket:
    """Минимальный RFC 6455 клиент для текстового Centrifugo-протокола."""

    def __init__(self):
        raw = socket.create_connection((CENTRIFUGO_HOST, 443), timeout=20)
        self.sock = ssl.create_default_context().wrap_socket(
            raw, server_hostname=CENTRIFUGO_HOST
        )
        self.sock.settimeout(35)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            "GET " + CENTRIFUGO_PATH + " HTTP/1.1\r\n"
            "Host: " + CENTRIFUGO_HOST + "\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Key: " + key + "\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "Origin: https://www.donationalerts.com\r\n\r\n"
        ).encode("ascii")
        self.sock.sendall(request)
        headers = bytearray()
        while not headers.endswith(b"\r\n\r\n"):
            part = self.sock.recv(1)
            if not part or len(headers) > 16_384:
                self.close()
                raise DonationAlertsError("Не удалось установить WebSocket-соединение")
            headers.extend(part)
        header_text = headers.decode("latin1", "replace")
        expected = base64.b64encode(
            hashlib.sha1((key + _WS_GUID).encode("ascii")).digest()
        ).decode("ascii")
        if " 101 " not in header_text.split("\r\n", 1)[0]:
            self.close()
            raise DonationAlertsError("DonationAlerts не принял WebSocket-подключение")
        lowered = header_text.lower()
        if "sec-websocket-accept: " + expected.lower() not in lowered:
            self.close()
            raise DonationAlertsError("Неверный ответ WebSocket handshake")

    def close(self):
        sock = getattr(self, "sock", None)
        self.sock = None
        if sock:
            try:
                sock.close()
            except OSError:
                pass

    def send_frame(self, opcode, payload=b""):
        if self.sock is None:
            raise DonationAlertsError("WebSocket закрыт")
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        length = len(payload)
        mask = os.urandom(4)
        first = bytes((0x80 | (opcode & 0x0F),))
        if length < 126:
            header = first + bytes((0x80 | length,))
        elif length < 65_536:
            header = first + bytes((0x80 | 126,)) + struct.pack("!H", length)
        else:
            header = first + bytes((0x80 | 127,)) + struct.pack("!Q", length)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.sock.sendall(header + mask + masked)

    def send_json(self, value):
        self.send_frame(1, json.dumps(value, ensure_ascii=False, separators=(",", ":")))

    def ping(self):
        self.send_frame(9, b"yapdome")

    def _read_exact(self, size):
        chunks = bytearray()
        while len(chunks) < size:
            part = self.sock.recv(size - len(chunks))
            if not part:
                raise DonationAlertsError("WebSocket-соединение закрыто сервером")
            chunks.extend(part)
        return bytes(chunks)

    def recv_text(self):
        fragments = []
        active_opcode = None
        while True:
            first, second = self._read_exact(2)
            fin = bool(first & 0x80)
            opcode = first & 0x0F
            masked = bool(second & 0x80)
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._read_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read_exact(8))[0]
            if length > 1_048_576:
                raise DonationAlertsError("Слишком большое сообщение WebSocket")
            mask = self._read_exact(4) if masked else b""
            payload = self._read_exact(length) if length else b""
            if masked:
                payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
            if opcode == 8:
                raise DonationAlertsError("DonationAlerts закрыл WebSocket")
            if opcode == 9:
                self.send_frame(10, payload)
                continue
            if opcode == 10:
                continue
            if opcode in (1, 2):
                active_opcode = opcode
                fragments = [payload]
            elif opcode == 0 and active_opcode is not None:
                fragments.append(payload)
            else:
                continue
            if fin:
                if active_opcode != 1:
                    active_opcode = None
                    fragments = []
                    continue
                try:
                    return b"".join(fragments).decode("utf-8")
                except UnicodeDecodeError:
                    raise DonationAlertsError("Получено некорректное текстовое сообщение") from None
            active_opcode = 1 if active_opcode == 1 else active_opcode


class DonationAlerts:
    """OAuth-клиент и фоновая подписка на новые донаты."""

    def __init__(self, host="127.0.0.1", port=13180, config_path=CONFIG_PATH):
        self.host = host
        self.port = int(port)
        self.redirect_uri = "http://" + host + ":" + str(port) + "/donationalerts/callback"
        self.path = Path(config_path)
        self.lock = threading.RLock()
        self.event_condition = threading.Condition(self.lock)
        # Millisecond epoch keeps SSE cursors valid across server restarts.
        self.event_sequence = int(time.time() * 1000)
        self.stop_event = threading.Event()
        self.thread = None
        self.socket = None
        self.pending_state = None
        self.pending_created = 0
        self.connected = False
        self.username = ""
        self.last_error = ""
        self.last_event_at = ""
        # Счётчики относятся к входящему потоку после подтверждения подписки.
        self.ws_messages_received = 0
        self.channel_publications_received = 0
        self.donations_parsed = 0
        self.donations_rejected = 0
        self.last_ws_message_at = ""
        self.last_publication_at = ""
        self.last_rejection_reason = ""
        self.events = deque(maxlen=200)
        self.seen_ids = deque(maxlen=2000)
        self.seen_set = set()
        self.config = self._load()
        if self.config.get("access_token") or self.config.get("refresh_token"):
            self._start_listener()

    def _load(self):
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            pass
        if not self.path.exists():
            return {}
        try:
            record = json.loads(self.path.read_text("utf-8"))
            return record if isinstance(record, dict) else {}
        except (ValueError, OSError):
            raise DonationAlertsError(
                "Файл DonationAlerts повреждён: " + str(self.path)
            ) from None

    def _save(self):
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        temp = self.path.with_suffix(".tmp-" + secrets.token_hex(4))
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self.config, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.path)
            os.chmod(self.path, 0o600)
        finally:
            if temp.exists():
                temp.unlink()

    def status(self):
        with self.lock:
            return {
                "configured": bool(self.config.get("client_id") and self.config.get("client_secret")),
                "authorized": bool(self.config.get("access_token") or self.config.get("refresh_token")),
                "connected": self.connected,
                "client_id": self.config.get("client_id", ""),
                "username": self.username,
                "redirect_uri": self.redirect_uri,
                "last_error": self.last_error,
                "last_event_at": self.last_event_at,
                "queued_events": len(self.events),
                "ws_messages_received": self.ws_messages_received,
                "channel_publications_received": self.channel_publications_received,
                "donations_parsed": self.donations_parsed,
                "donations_rejected": self.donations_rejected,
                "last_ws_message_at": self.last_ws_message_at,
                "last_publication_at": self.last_publication_at,
                "last_rejection_reason": self.last_rejection_reason,
                "auth_pending": bool(self.pending_state and time.time() - self.pending_created < 600),
            }

    def _record_ws_message(self, channel_publication=False):
        """Фиксирует только счётчики и время — без тела WS-сообщения."""
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        with self.lock:
            self.ws_messages_received += 1
            self.last_ws_message_at = now
            if channel_publication:
                self.channel_publications_received += 1
                self.last_publication_at = now

    def _record_publication_result(self, donation, reason=""):
        with self.lock:
            if donation is not None:
                self.donations_parsed += 1
            else:
                self.donations_rejected += 1
                self.last_rejection_reason = (
                    _safe_text(reason, 140) or "неизвестная причина отклонения"
                )

    def set_error(self, message):
        with self.lock:
            self.last_error = _safe_text(message, 240) or "Ошибка авторизации DonationAlerts"

    def connect(self, client_id, client_secret):
        client_id = str(client_id or "").strip()
        client_secret = str(client_secret or "").strip()
        if not client_id or len(client_id) > 80 or not client_id.isdigit():
            raise DonationAlertsError("Client ID должен состоять из цифр приложения DonationAlerts")
        self._stop_listener()
        with self.lock:
            old_id = self.config.get("client_id", "")
            if not client_secret and old_id != client_id:
                raise DonationAlertsError("Для нового Client ID нужен Client Secret")
            if client_secret and len(client_secret) > 512:
                raise DonationAlertsError("Client Secret слишком длинный")
            if old_id != client_id:
                self.config = {}
            self.config["client_id"] = client_id
            if client_secret:
                self.config["client_secret"] = client_secret
            if not self.config.get("client_secret"):
                raise DonationAlertsError("Введи Client Secret своего OAuth-приложения")
            self.config.pop("access_token", None)
            self.config.pop("refresh_token", None)
            self.config.pop("expires_at", None)
            self._save()
            self.pending_state = secrets.token_urlsafe(32)
            self.pending_created = time.time()
            query = urllib.parse.urlencode({
                "client_id": client_id,
                "redirect_uri": self.redirect_uri,
                "response_type": "code",
                "scope": SCOPES,
                "state": self.pending_state,
            })
            self.last_error = ""
            return {
                "url": AUTHORIZE_URL + "?" + query,
                "redirect_uri": self.redirect_uri,
            }

    def finish_oauth(self, query):
        if query.get("error"):
            description = query.get("error_description", ["Авторизация отклонена"])[0]
            raise DonationAlertsError(_safe_text(description, 200))
        code = (query.get("code") or [""])[0]
        state = (query.get("state") or [""])[0]
        with self.lock:
            if not self.pending_state or time.time() - self.pending_created > 600:
                raise DonationAlertsError("Срок авторизации истёк. Нажми «Подключить» ещё раз.")
            if not secrets.compare_digest(str(state), self.pending_state):
                raise DonationAlertsError("Не совпал OAuth state. Повтори подключение.")
            if not code:
                raise DonationAlertsError("DonationAlerts не вернул код авторизации")
            payload = {
                "grant_type": "authorization_code",
                "client_id": self.config["client_id"],
                "client_secret": self.config["client_secret"],
                "redirect_uri": self.redirect_uri,
                "code": code,
            }
        token = self._request_json(TOKEN_URL, payload, form=True)
        token = token.get("data", token) if isinstance(token, dict) else {}
        if not isinstance(token, dict) or not token.get("access_token"):
            raise DonationAlertsError("DonationAlerts не вернул access_token")
        with self.lock:
            self.config["access_token"] = token["access_token"]
            if token.get("refresh_token"):
                self.config["refresh_token"] = token["refresh_token"]
            self.config["expires_at"] = time.time() + int(token.get("expires_in", 3600))
            self.pending_state = None
            self.pending_created = 0
            self.last_error = ""
            self._save()
        self._start_listener()

    def _request_json(self, url, payload=None, form=False, access_token=None):
        headers = {"Accept": "application/json"}
        body = None
        if payload is not None:
            if form:
                body = urllib.parse.urlencode(payload).encode("utf-8")
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            else:
                body = json.dumps(payload).encode("utf-8")
                headers["Content-Type"] = "application/json"
        if access_token:
            headers["Authorization"] = "Bearer " + access_token
        request = urllib.request.Request(url, data=body, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                raw = response.read(1_000_001)
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read(32_000).decode("utf-8", "replace"))
                message = payload.get("message") or payload.get("error_description") or payload.get("error")
            except (ValueError, AttributeError):
                message = None
            raise DonationAlertsError(
                "DonationAlerts API: " + _safe_text(message or ("HTTP " + str(exc.code)), 180)
            ) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise DonationAlertsError(
                "Не удалось связаться с DonationAlerts: " + _safe_text(exc, 150)
            ) from None
        if len(raw) > 1_000_000:
            raise DonationAlertsError("Ответ DonationAlerts слишком большой")
        if not raw:
            return {}
        try:
            value = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise DonationAlertsError("DonationAlerts вернул некорректный JSON") from None
        if not isinstance(value, dict):
            raise DonationAlertsError("Неожиданный формат ответа DonationAlerts")
        return value

    def _access_token(self):
        with self.lock:
            expires_at = float(self.config.get("expires_at") or 0)
            access_token = self.config.get("access_token")
            refresh_token = self.config.get("refresh_token")
            if access_token and expires_at > time.time() + 90:
                return access_token
            if not refresh_token:
                raise DonationAlertsError("Нужна повторная авторизация DonationAlerts")
            payload = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self.config["client_id"],
                "client_secret": self.config["client_secret"],
                "scope": SCOPES,
            }
        token = self._request_json(TOKEN_URL, payload, form=True)
        token = token.get("data", token)
        if not token.get("access_token"):
            raise DonationAlertsError("Не удалось обновить токен DonationAlerts")
        with self.lock:
            self.config["access_token"] = token["access_token"]
            if token.get("refresh_token"):
                self.config["refresh_token"] = token["refresh_token"]
            self.config["expires_at"] = time.time() + int(token.get("expires_in", 3600))
            self._save()
            return self.config["access_token"]

    def _api(self, path, payload=None):
        token = self._access_token()
        return self._request_json(API_ROOT + path, payload, access_token=token)

    def _start_listener(self):
        self._stop_listener()
        self.stop_event.clear()
        self.thread = threading.Thread(
            target=self._listener_loop, name="DonationAlerts-Centrifugo", daemon=True
        )
        self.thread.start()

    def _stop_listener(self):
        self.stop_event.set()
        sock = self.socket
        if sock is not None:
            sock.close()
        thread = self.thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2)
        self.thread = None
        self.socket = None
        self.connected = False

    def disconnect(self):
        self._stop_listener()
        with self.lock:
            self.config = {}
            self.pending_state = None
            self.username = ""
            self.last_error = ""
            self.events.clear()
            self.seen_ids.clear()
            self.seen_set.clear()
            self._save()
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass

    def close(self):
        self._stop_listener()

    def pop_events(self):
        """Legacy one-shot drain; kept for compatibility with older clients."""
        with self.lock:
            result = [{key: value for key, value in event.items() if key != "_stream_id"}
                      for event in self.events]
            self.events.clear()
            return result

    def events_since(self, last_event_id=0, timeout=15):
        """Return buffered events newer than the SSE cursor, waiting for new data."""
        try:
            cursor = max(0, int(last_event_id or 0))
        except (TypeError, ValueError):
            cursor = 0
        with self.event_condition:
            matches = [event for event in self.events
                       if event.get("_stream_id", 0) > cursor]
            if not matches:
                self.event_condition.wait(max(0, min(float(timeout), 30)))
                matches = [event for event in self.events
                           if event.get("_stream_id", 0) > cursor]
            return [(event["_stream_id"],
                     {key: value for key, value in event.items() if key != "_stream_id"})
                    for event in matches]

    def _wait_response(self, ws, request_id, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                message = json.loads(ws.recv_text())
            except socket.timeout:
                continue
            if isinstance(message, dict) and message.get("id") == request_id:
                if message.get("error"):
                    raise DonationAlertsError("Centrifugo: " + _safe_text(message["error"], 160))
                return message.get("result") or {}
        raise DonationAlertsError("Истекло время ожидания ответа Centrifugo")

    def _listen_once(self):
        profile = self._api("/user/oauth").get("data", {})
        if not isinstance(profile, dict) or not profile.get("id") or not profile.get("socket_connection_token"):
            raise DonationAlertsError("Не удалось получить профиль и Centrifugo token")
        channel = "$alerts:donation_" + str(profile["id"])
        ws = _WebSocket()
        self.socket = ws
        try:
            ws.send_json({"params": {"token": profile["socket_connection_token"]}, "id": 1})
            connection = self._wait_response(ws, 1)
            client_id = connection.get("client")
            if not client_id:
                raise DonationAlertsError("Centrifugo не вернул client ID")
            subscription = self._api("/centrifuge/subscribe", {
                "channels": [channel],
                "client": client_id,
            })
            entries = subscription.get("channels") or []
            entry = next((item for item in entries if item.get("channel") == channel), None)
            if not entry or not entry.get("token"):
                raise DonationAlertsError("DonationAlerts не выдал токен канала донатов")
            ws.send_json({
                "params": {"channel": channel, "token": entry["token"]},
                "method": 1,
                "id": 2,
            })
            self._wait_response(ws, 2)
            with self.lock:
                self.connected = True
                self.username = _safe_text(profile.get("name") or profile.get("code"), 64)
                self.last_error = ""
            while not self.stop_event.is_set():
                try:
                    raw = ws.recv_text()
                except socket.timeout:
                    ws.ping()
                    continue
                # Это сообщения уже после handshake и подписки на канал.
                try:
                    message = json.loads(raw)
                except (TypeError, ValueError):
                    self._record_ws_message()
                    continue
                push = _publication_envelope(message)
                is_channel_publication = isinstance(push, dict) and push.get("channel") == channel
                self._record_ws_message(channel_publication=is_channel_publication)
                if not is_channel_publication:
                    continue
                donation, reason = _parse_donation_publication(message, channel)
                self._record_publication_result(donation, reason)
                if donation:
                    self._push_event(donation)
        finally:
            ws.close()
            if self.socket is ws:
                self.socket = None
            with self.lock:
                self.connected = False

    def _push_event(self, donation):
        with self.lock:
            event_id = donation["id"]
            if event_id in self.seen_set:
                return
            if len(self.seen_ids) == self.seen_ids.maxlen:
                oldest = self.seen_ids[0]
                self.seen_set.discard(oldest)
            self.seen_ids.append(event_id)
            self.seen_set.add(event_id)
            self.event_sequence += 1
            event = dict(donation)
            event["_stream_id"] = self.event_sequence
            self.events.append(event)
            self.last_event_at = time.strftime("%Y-%m-%d %H:%M:%S")
            self.event_condition.notify_all()

    def _listener_loop(self):
        while not self.stop_event.is_set():
            try:
                self._listen_once()
            except Exception as exc:
                with self.lock:
                    self.connected = False
                    self.last_error = _safe_text(exc, 240) or type(exc).__name__
            if not self.stop_event.is_set():
                self.stop_event.wait(4)


__all__ = ["DonationAlerts", "DonationAlertsError", "extract_donation"]
