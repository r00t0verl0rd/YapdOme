"""Авторизация: OAuth PKCE для подписки ChatGPT, ключи провайдеров, сессии."""

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from .config import HOST, PORT
from .llm import BridgeError, b64encode, json_request, verify_jwt
from .llm import ISSUER, RESOURCE

AUTHORIZE_URL = ISSUER + "/api/accounts/authorize"
TOKEN_URL = ISSUER + "/api/accounts/oauth/token"
CONFIG_DIR = Path.home() / ".triad-dialogue"
CREDENTIAL_PATH = CONFIG_DIR / "accounts.json"


class State:
    """Локальное состояние подключения: аккаунты ChatGPT и ключи провайдеров."""

    def __init__(self, credential_path=CREDENTIAL_PATH):
        self.lock = threading.RLock()
        # Обновление токена сериализовано; глобальный лок не держится во время сети.
        self.refresh_lock = threading.Lock()
        self.pending = None
        self.last_error = ""
        self.active_calls = {}
        self.path = credential_path
        self.credentials = self.load()

    def load(self):
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            pass
        if self.path.exists():
            try:
                record = json.loads(self.path.read_text("utf-8"))
                if isinstance(record, dict) and isinstance(record.get("accounts"), dict):
                    record.setdefault("host_id", "urn:uuid:" + str(uuid.uuid4()))
                    record.setdefault("provider", "chatgpt")
                    record.setdefault("deepseek", {})
                    return record
            except (ValueError, OSError):
                raise BridgeError("Файл сохранённых аккаунтов повреждён. Сделай резервную копию: " + str(self.path))
        record = {"host_id": "urn:uuid:" + str(uuid.uuid4()), "active": None, "accounts": {},
                  "provider": "chatgpt", "deepseek": {}}
        self.credentials = record
        self.save()
        return record

    def save(self):
        temp = self.path.with_suffix(".tmp-" + secrets.token_hex(4))
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.credentials, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, self.path)
            os.chmod(self.path, 0o600)
        finally:
            if temp.exists():
                temp.unlink()

    def selected(self):
        key = self.credentials.get("active")
        return self.credentials["accounts"].get(key) if key else None

    def provider(self):
        with self.lock:
            return self.credentials.get("provider", "chatgpt")

    def set_provider(self, name):
        if name not in ("chatgpt", "deepseek"):
            raise BridgeError("Неизвестный провайдер")
        with self.lock:
            self.credentials["provider"] = name
            self.save()

    def deepseek_key(self):
        with self.lock:
            return self.credentials.get("deepseek", {}).get("api_key") or None

    def set_deepseek_key(self, key):
        if not isinstance(key, str) or not key.strip() or len(key.strip()) > 200:
            raise BridgeError("Некорректный API-ключ DeepSeek")
        with self.lock:
            self.credentials.setdefault("deepseek", {})["api_key"] = key.strip()
            self.credentials["provider"] = "deepseek"
            self.save()

    def clear_deepseek(self):
        with self.lock:
            self.credentials.pop("deepseek", None)
            if self.credentials.get("provider") == "deepseek":
                self.credentials["provider"] = "chatgpt"
            self.save()

    def status(self):
        with self.lock:
            account = self.selected()
            return {
                "connected": bool(account and account.get("access_token") and
                                  "chatgpt.tokens.use.direct" in account.get("scopes", [])),
                "deepseek_connected": bool(self.credentials.get("deepseek", {}).get("api_key")),
                "provider": self.credentials.get("provider", "chatgpt"),
                "account": account.get("email", "Аккаунт ChatGPT") if account else None,
                "has_saved_account": bool(self.credentials.get("active") and account),
                "recoverable": bool(self.credentials.get("registration_pending")),
                "auth_pending": bool(self.pending and time.time() - self.pending["created"] < 600),
                "auth_error": self.last_error,
            }

    def start_auth(self, mode="auto"):
        """Вход в один клик: повторная авторизация того же аккаунта или регистрация другого."""
        if mode not in ("auto", "switch"):
            raise BridgeError("Некорректный режим авторизации")
        with self.lock:
            candidate = self.credentials.get("registration_pending")
            old_id = self.credentials.get("active")
            old_account = self.credentials["accounts"].get(old_id) if old_id else None
            cid = None
            account = None
            if mode == "switch":
                # Явная смена аккаунта не наследует регистрацию другого пользователя.
                self.credentials.pop("registration_pending", None)
                self.save()
            elif (isinstance(candidate, dict) and isinstance(candidate.get("client_id"), str)
                  and candidate["client_id"].startswith("oaiapp_")):
                # Выданная регистрация переживает неудачный обмен кода и позволяет повторить вход.
                cid = candidate["client_id"]
            elif old_account:
                cid = old_id
                account = old_account
            verifier = b64encode(secrets.token_bytes(48))
            nonce = secrets.token_urlsafe(32)
            state = secrets.token_urlsafe(32)
            redirect = f"http://{HOST}:{PORT}/auth/callback"
            self.pending = {"state": state, "nonce": nonce, "verifier": verifier,
                            "redirect": redirect, "client_id": cid,
                            "created": time.time(), "mode": mode}
            self.last_error = ""
            args = {"client_id": cid or "dynamic_agent_client", "response_type": "code",
                    "redirect_uri": redirect,
                    "scope": "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct",
                    "resource": RESOURCE, "state": state, "nonce": nonce,
                    "ext_agent_host_id": self.credentials["host_id"],
                    "code_challenge_method": "S256",
                    "code_challenge": b64encode(hashlib.sha256(verifier.encode()).digest())}
            if account:
                if account.get("id_token"):
                    args["id_token_hint"] = account["id_token"]
                if account.get("email"):
                    args["login_hint"] = account["email"]
            elif cid is None:
                args["agent_name_hint"] = "TRIAD Live"
            return AUTHORIZE_URL + "?" + urllib.parse.urlencode(args)

    def finish_auth(self, query):
        with self.lock:
            pending = self.pending
            if not pending or time.time() - pending["created"] > 600:
                raise BridgeError("Время входа истекло. Нажми «Войти» ещё раз")
            returned_state = query.get("state", [""])[0]
            if not isinstance(returned_state, str) or not hmac.compare_digest(
                    returned_state.encode("utf-8", "replace"), pending["state"].encode("ascii")):
                # Подделанный колбэк не должен разрушать настоящую попытку входа.
                raise BridgeError("Проверка OAuth state не пройдена")
            self.pending = None
            if "error" in query:
                raise BridgeError("Вход отклонён: " + str(query["error"][0])[:100])
            code = query.get("code", [""])[0]
            returned_id = query.get("client_id", [""])[0]
            cid = pending["client_id"]
            if not cid:
                if not isinstance(returned_id, str) or not returned_id.startswith("oaiapp_"):
                    raise BridgeError("OpenAI не вернул client_id новой регистрации")
                cid = returned_id
                self.credentials["registration_pending"] = {"client_id": cid, "created": time.time()}
                self.save()
            elif returned_id and cid != returned_id:
                raise BridgeError("OpenAI вернул другой client_id")
            if not code:
                raise BridgeError("OpenAI не вернул authorization code")
        # Лок STATE не держится во время обмена токена и получения JWKS.
        try:
            token_data = json_request(TOKEN_URL, {
                "grant_type": "authorization_code", "client_id": cid,
                "code": code, "code_verifier": pending["verifier"],
                "redirect_uri": pending["redirect"], "resource": RESOURCE}, form=True)
        except BridgeError as exc:
            if "invalid_grant" in str(exc).lower():
                raise BridgeError("Код авторизации истёк или уже использован (invalid_grant). "
                                  "Нажми «Войти» снова: повторим вход с новой PKCE-парой, "
                                  "сохранив выданный client_id") from None
            raise
        if not token_data.get("id_token"):
            raise BridgeError("OpenAI не вернул ID token")
        claims = verify_jwt(token_data["id_token"], cid, pending["nonce"])
        scopes = token_data.get("scope", "").split()
        if "chatgpt.tokens.use.direct" not in scopes:
            raise BridgeError("Доступ к подписке не разрешён; проверь разрешения ChatGPT")
        if not token_data.get("access_token"):
            raise BridgeError("OpenAI не выдал access_token")
        with self.lock:
            previous = self.credentials["accounts"].get(cid)
            if previous and previous.get("subject") != claims["sub"]:
                raise BridgeError("Другой аккаунт требует новой регистрации — выбери «Другой аккаунт»")
            account = {"client_id": cid, "subject": claims["sub"],
                       "email": claims.get("email") or (previous or {}).get("email") or "ChatGPT",
                       "id_token": token_data["id_token"], "access_token": token_data["access_token"],
                       "refresh_token": token_data.get("refresh_token") or (previous or {}).get("refresh_token"),
                       "expires_at": time.time() + int(token_data.get("expires_in", 3600)), "scopes": scopes}
            self.credentials["accounts"][cid] = account
            self.credentials["active"] = cid
            self.credentials.pop("registration_pending", None)
            self.save()
            self.last_error = ""
            return account

    def access_token(self):
        with self.refresh_lock:
            with self.lock:
                record = self.selected()
                if not record or "chatgpt.tokens.use.direct" not in record.get("scopes", []):
                    raise BridgeError("Сначала войди через ChatGPT и разреши использование подписки")
                if record.get("access_token") and float(record.get("expires_at", 0)) > time.time() + 90:
                    return record["access_token"]
                refresh = record.get("refresh_token")
                if not refresh:
                    raise BridgeError("Сессия истекла. Войди через ChatGPT снова")
                client_id = record["client_id"]
                subject = record.get("subject")
            # Медленная сеть никогда не держит главный лок состояния.
            new = json_request(TOKEN_URL, {"grant_type": "refresh_token", "client_id": client_id,
                                           "refresh_token": refresh, "resource": RESOURCE}, form=True)
            if not new.get("access_token"):
                raise BridgeError("OpenAI не обновил access_token; войди снова")
            with self.lock:
                record = self.selected()
                if not record or record.get("client_id") != client_id or record.get("subject") != subject:
                    raise BridgeError("Аккаунт изменён во время обновления токена")
                record["access_token"] = new["access_token"]
                record["refresh_token"] = new.get("refresh_token", refresh)
                record["expires_at"] = time.time() + int(new.get("expires_in", 3600))
                if "scope" in new:
                    record["scopes"] = new["scope"].split()
                if "chatgpt.tokens.use.direct" not in record.get("scopes", []):
                    raise BridgeError("Разрешение ChatGPT plan usage отозвано — войди снова")
                self.save()
                return record["access_token"]

    def logout(self):
        with self.lock:
            account = self.selected()
            if not account:
                return True
            refresh = account.get("refresh_token")
            cid = account["client_id"]
            revoked = not refresh
            if refresh:
                try:
                    discover = json_request(ISSUER + "/.well-known/openid-configuration")
                    url = discover["revocation_endpoint"]
                    if not url.startswith(ISSUER + "/"):
                        raise BridgeError("Непроверенный endpoint отзыва токена")
                    request = urllib.request.Request(url, data=urllib.parse.urlencode({"token": refresh,
                                     "token_type_hint": "refresh_token", "client_id": cid}).encode(),
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
                    with urllib.request.urlopen(request, timeout=8) as response:
                        revoked = response.status == 200
                except Exception:
                    revoked = False
            for key in ("access_token", "refresh_token", "id_token"):
                account.pop(key, None)
            account.pop("expires_at", None)
            self.credentials["active"] = None
            self.save()
            return revoked


class LiveCall:
    """Отменяемый сетевой запрос: слот резервируется до начала ожидания токена."""

    def __init__(self):
        self.cancelled = threading.Event()
        self.response = None
        self.lock = threading.Lock()

    def attach(self, response):
        with self.lock:
            self.response = response
            if self.cancelled.is_set():
                response.close()

    def cancel(self):
        self.cancelled.set()
        with self.lock:
            if self.response:
                try:
                    self.response.close()
                except Exception:
                    pass
