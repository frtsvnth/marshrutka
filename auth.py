"""Пин-код на входе. Не про Google OAuth (это отдельный механизм в
youtube-pipelines/scripts/reauth_youtube.py) — просто закрывает саму
маршрутку от чужих, раз у неё появилась публичная страница.

Сессия — подписанная кука: `{exp}.{hmac_sha256(exp)}`, без внешних
зависимостей (jwt и подобное было бы избыточно для одного пин-кода).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time

from fastapi import Request
from fastapi.responses import RedirectResponse

AUTH_PIN = os.environ.get("AUTH_PIN", "")
AUTH_SECRET = os.environ.get("AUTH_SECRET", "")
SESSION_COOKIE = "mr_session"
SESSION_TTL_S = 30 * 24 * 3600  # 30 дней


def _sign(payload: str) -> str:
    return hmac.new(AUTH_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_session_value() -> str:
    exp = str(int(time.time()) + SESSION_TTL_S)
    return f"{exp}.{_sign(exp)}"


def _is_valid(value: str | None) -> bool:
    if not value or not AUTH_SECRET:
        return False
    exp, _, sig = value.partition(".")
    if not exp or not sig or not hmac.compare_digest(sig, _sign(exp)):
        return False
    try:
        return int(exp) > time.time()
    except ValueError:
        return False


def check_pin(pin: str) -> bool:
    return bool(AUTH_PIN) and hmac.compare_digest(pin.strip(), AUTH_PIN)


def is_authed(request: Request) -> bool:
    return _is_valid(request.cookies.get(SESSION_COOKIE))


def require_auth(request: Request) -> RedirectResponse | None:
    """None — доступ разрешён. Иначе — редирект на /login, который и надо
    вернуть из роута."""
    if is_authed(request):
        return None
    return RedirectResponse("/login", status_code=303)


def set_session_cookie(response: RedirectResponse) -> None:
    response.set_cookie(
        SESSION_COOKIE, make_session_value(), max_age=SESSION_TTL_S,
        httponly=True, samesite="lax", secure=True,
    )


def clear_session_cookie(response: RedirectResponse) -> None:
    response.delete_cookie(SESSION_COOKIE)
