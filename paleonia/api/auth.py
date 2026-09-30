"""Sessão assinada para o login local do PaleonIA."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from paleonia.config import Settings

COOKIE = "paleonia_session"
TTL_SECONDS = 60 * 60 * 24 * 7


def enabled(settings: Settings) -> bool:
    return bool(settings.auth_password)


def _secret(settings: Settings) -> str:
    return settings.auth_secret or settings.auth_password


def credentials_match(settings: Settings, username: str, password: str) -> bool:
    user_ok = hmac.compare_digest(username, settings.auth_username)
    pass_ok = hmac.compare_digest(password, settings.auth_password)
    return user_ok and pass_ok


def issue_token(settings: Settings, username: str, now: float | None = None) -> str:
    payload = {"u": username, "exp": int(now if now is not None else time.time()) + TTL_SECONDS}
    raw = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = hmac.new(_secret(settings).encode(), raw.encode(), hashlib.sha256).hexdigest()
    return f"{raw}.{signature}"


def read_username(token: str, settings: Settings, now: float | None = None) -> str | None:
    raw, separator, signature = token.partition(".")
    if not raw or not separator or not signature:
        return None
    expected = hmac.new(_secret(settings).encode(), raw.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    padded = raw + "=" * (-len(raw) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    expires = payload.get("exp")
    username = payload.get("u")
    if not isinstance(expires, int) or not isinstance(username, str) or not username:
        return None
    if expires < int(now if now is not None else time.time()):
        return None
    return username
