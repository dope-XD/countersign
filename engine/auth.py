"""Staff access: a shared PIN unlocks the agent console, fraud desk, demo panel and metrics.

Browsers exchange the PIN once for a signed HttpOnly cookie. Scripts (the IndiaCall
simulator, tests) send the PIN in an `X-Staff-Pin` header. Customer surfaces (bank app,
softphone, approvals, payments) never need it.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time

from fastapi import HTTPException, Request, WebSocket

from engine.config import settings

log = logging.getLogger(__name__)

COOKIE = "cs_staff"
HEADER = "x-staff-pin"
TTL = 7 * 24 * 3600


def _persisted(name: str, make) -> str:
    p = settings.runtime_dir / name
    if not p.exists():
        p.write_text(make())
    return p.read_text().strip()


def staff_pin() -> str:
    if settings.staff_pin:
        return settings.staff_pin
    return _persisted("staff_pin.txt", lambda: f"{secrets.randbelow(10**6):06d}")


_SECRET = _persisted("cookie_secret.key", lambda: secrets.token_hex(32)).encode()


def pin_ok(pin: str | None) -> bool:
    return bool(pin) and hmac.compare_digest(pin.encode(), staff_pin().encode())


def make_cookie() -> str:
    exp = str(int(time.time()) + TTL)
    sig = hmac.new(_SECRET, exp.encode(), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def cookie_ok(value: str | None) -> bool:
    if not value or "." not in value:
        return False
    exp, sig = value.split(".", 1)
    good = hmac.new(_SECRET, exp.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, good) and exp.isdigit() and int(exp) > time.time()


def is_staff(conn: Request | WebSocket) -> bool:
    return cookie_ok(conn.cookies.get(COOKIE)) or pin_ok(conn.headers.get(HEADER))


def require_staff(request: Request) -> None:
    """FastAPI dependency for staff-only HTTP routes."""
    if not is_staff(request):
        raise HTTPException(401, "staff PIN required")
