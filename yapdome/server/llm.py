"""Транспортный слой LLM: HTTP-JSON, SSE, JWT, ошибки моста.

Чистые функции без состояния эфира; запросы к провайдерам собираются в
:mod:`yapdome.server.app`, где доступен глобальный STATE.
"""

import base64
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request

ISSUER = "https://auth.openai.com"
JWKS_URL = ISSUER + "/.well-known/jwks.json"
RESOURCE = "https://api.openai.com/v1"
API_URL = RESOURCE
DEEPSEEK_URL = "https://api.deepseek.com"


class BridgeError(Exception):
    pass


def b64decode(value):
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def b64encode(data):
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def json_request(url, data=None, token=None, *, timeout=18, form=False):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    payload = None
    if data is not None:
        if form:
            payload = urllib.parse.urlencode(data).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            payload = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=payload, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            raw = reply.read(3_000_000)
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        message = ""
        try:
            parsed = json.loads(exc.read(10000))
            detail = parsed.get("error", parsed)
            message = detail.get("message", str(detail)) if isinstance(detail, dict) else str(detail)
        except Exception:
            message = exc.reason or "HTTP error"
        raise BridgeError(f"OpenAI HTTP {exc.code}: {message}") from None


def sse_events(source, *, deadline=None):
    """Разбирает ограниченный поток SSE один раз для всех трёх линий модели.

    Единый счётчик байтов не позволяет повторно сканировать строки данных.
    Генератор выдаёт только целые JSON-события; комментарии и [DONE] игнорируются.
    """
    parts = []
    size = 0
    for raw in source:
        if deadline is not None and time.monotonic() - deadline > 0:
            raise BridgeError("Максимальная длительность ответа 65 секунд")
        if len(raw) > 480_000:
            raise BridgeError("Слишком длинная строка SSE")
        row = raw.decode("utf-8", "replace").rstrip("\r\n")
        if len(row) > 120_000:
            raise BridgeError("Слишком длинная строка SSE")
        if row.startswith("data:"):
            value = row[5:].lstrip(" ")
            size += len(value)
            if size > 120_000:
                raise BridgeError("Слишком длинное SSE-событие")
            parts.append(value)
        elif not row and parts:
            packet = "\n".join(parts)
            parts.clear()
            size = 0
            if packet == "[DONE]":
                continue
            try:
                event = json.loads(packet)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                yield event


# Проверка RS256 (RFC 7518) средствами стандартной библиотеки; без «alg=none».
DER_SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


def verify_jwt(token, audience, nonce, jwks=None):
    try:
        head_enc, body_enc, sig_enc = token.split(".")
        header = json.loads(b64decode(head_enc))
        claims = json.loads(b64decode(body_enc))
        signing_input = (head_enc + "." + body_enc).encode("ascii")
        signature = b64decode(sig_enc)
    except Exception as exc:
        raise BridgeError("ID token имеет некорректный формат") from exc
    if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
        raise BridgeError("Неподдерживаемый алгоритм подписи ID token (требуется RS256)")
    document = jwks if jwks is not None else json_request(JWKS_URL)
    if not isinstance(document, dict) or not isinstance(document.get("keys"), list):
        raise BridgeError("Неверный формат JWKS")
    keys = document["keys"]
    key = next((k for k in keys if isinstance(k, dict) and k.get("kid") == header["kid"]
                and k.get("kty") == "RSA" and k.get("use", "sig") == "sig"
                and k.get("alg", "RS256") == "RS256"), None)
    if key is None:
        raise BridgeError("Не найден публичный ключ для проверки ID token")
    try:
        n = int.from_bytes(b64decode(key["n"]), "big")
        e = int.from_bytes(b64decode(key["e"]), "big")
        klen = (n.bit_length() + 7) // 8
        if len(signature) != klen or not (0 < e < 2**32) or n.bit_length() < 2048:
            raise ValueError("invalid RSA key")
        encoded = pow(int.from_bytes(signature, "big"), e, n).to_bytes(klen, "big")
        digest_info = DER_SHA256_PREFIX + hashlib.sha256(signing_input).digest()
        padlen = klen - len(digest_info) - 3
        valid = padlen >= 8 and hmac.compare_digest(encoded, b"\x00\x01" + b"\xff" * padlen + b"\x00" + digest_info)
        if not valid:
            raise ValueError("invalid signature")
    except Exception as exc:
        raise BridgeError("Подпись ID token не прошла проверку") from exc
    now = time.time()
    if claims.get("iss") != ISSUER:
        raise BridgeError("Неверный issuer ID token")
    aud = claims.get("aud")
    if (audience not in aud) if isinstance(aud, list) else aud != audience:
        raise BridgeError("ID token выпущен для другого клиента")
    if not isinstance(claims.get("exp"), (int, float)) or claims["exp"] < now - 5:
        raise BridgeError("ID token просрочен")
    if not isinstance(claims.get("iat"), (int, float)) or claims["iat"] > now + 60:
        raise BridgeError("Неверное время ID token")
    if not isinstance(claims.get("sub"), str) or not claims["sub"]:
        raise BridgeError("В ID token нет идентификатора аккаунта")
    if not hmac.compare_digest(str(claims.get("nonce", "")).encode("utf-8", "replace"), nonce.encode("ascii")):
        raise BridgeError("Несовпадение nonce при авторизации")
    return claims
