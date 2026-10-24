"""Who may do what.

Staff: a shared PIN unlocks the agent console, fraud desk, demo panel and metrics. Browsers
exchange it once for a signed HttpOnly cookie; scripts (the IndiaCall simulator, tests) send
it in an `X-Staff-Pin` header. Ten wrong PINs in five minutes from one client lock PIN
checks for that client for five minutes, and 100 from everyone together lock them for all
(cookies already issued keep working). One stranger can't lock the staff out, and nobody
can guess the 8-digit PIN at speed.

Customers: the CS Bank Android app signs up (or a team phone claims a seeded account with the
staff PIN) and gets a device token (`X-Device-Token`) naming its customer. Everything the app
does needs it: pay, family, receive app events. Saying "Yes" to an approval also needs a
signature from the phone's Keystore key (engine/stepup/devicekeys.py), so a stolen token alone
can't approve anything. The softphone needs nothing: it is the caller's phone, and the caller
may be the attacker.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from collections import deque

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
    return _persisted("staff_pin.txt", lambda: f"{secrets.randbelow(10**8):08d}")


_SECRET = _persisted("cookie_secret.key", lambda: secrets.token_hex(32)).encode()


MAX_FAILS, MAX_FAILS_ALL, FAIL_WINDOW, LOCKOUT = 10, 100, 300.0, 300.0
ALL = "*"  # the lockout key every wrong PIN also counts towards
_fails: dict[str, deque[float]] = {}
_locked_until: dict[str, float] = {}


def client_key(conn: Request | WebSocket) -> str:
    """Who is guessing: the address the nearest proxy (the tunnel) saw, else the socket peer.
    The last X-Forwarded-For entry is the one the proxy added; earlier ones are the client's word."""
    fwd = conn.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[-1].strip()
    peer = getattr(conn, "client", None)
    return peer.host if peer else "?"


def pin_ok(pin: str | None, client: str = "?") -> bool:
    """Check a staff PIN. A wrong PIN counts towards this client's lockout and the shared one."""
    if not pin:
        return False
    now = time.time()
    if pin_locked(client):
        return False
    if hmac.compare_digest(pin.encode(), staff_pin().encode()):
        return True
    for key, limit in ((client, MAX_FAILS), (ALL, MAX_FAILS_ALL)):
        fails = _fails.setdefault(key, deque())
        fails.append(now)
        while fails and fails[0] < now - FAIL_WINDOW:
            fails.popleft()
        if len(fails) >= limit:
            _locked_until[key] = now + LOCKOUT
            fails.clear()
            log.warning("%d wrong staff PINs in %.0f s from %s: PIN checks locked for %.0f s", limit, FAIL_WINDOW, key, LOCKOUT)
    if len(_fails) > 10_000:  # forget quiet clients so spoofed addresses can't grow this forever
        for key in [k for k, d in _fails.items() if not d or d[-1] < now - FAIL_WINDOW]:
            del _fails[key]
    return False


def pin_locked(client: str = "?") -> bool:
    now = time.time()
    return now < _locked_until.get(client, 0.0) or now < _locked_until.get(ALL, 0.0)


def reset_pin_lockout() -> None:
    _fails.clear()
    _locked_until.clear()


def _sign(payload: str) -> str:
    return hmac.new(_SECRET, payload.encode(), hashlib.sha256).hexdigest()


def make_cookie(subject: str = "staff") -> str:
    exp = str(int(time.time()) + TTL)
    return f"{exp}.{_sign(f'{subject}:{exp}')}"


def cookie_ok(value: str | None, subject: str = "staff") -> bool:
    if not value or "." not in value:
        return False
    exp, sig = value.split(".", 1)
    return exp.isdigit() and int(exp) > time.time() and hmac.compare_digest(sig.encode(), _sign(f"{subject}:{exp}").encode())


def is_staff(conn: Request | WebSocket) -> bool:
    return cookie_ok(conn.cookies.get(COOKIE)) or pin_ok(conn.headers.get(HEADER), client_key(conn))


def require_staff(request: Request) -> None:
    """FastAPI dependency for staff-only HTTP routes."""
    if not is_staff(request):
        locked = pin_locked(client_key(request))
        raise HTTPException(401, "staff PIN required (PIN checks are locked for a few minutes)" if locked else "staff PIN required")


# ---------------------------------------------------------------- customer phones
DEVICE_HEADER = "x-device-token"


def make_device_token(customer_id: str) -> str:
    """`<customer>.<expiry>.<signature>`: the app sends it with every request."""
    exp = str(int(time.time()) + TTL)
    return f"{customer_id}.{exp}.{_sign(f'device:{customer_id}:{exp}')}"


def device_customer(conn: Request | WebSocket) -> str | None:
    """The customer whose app sent this request, if its device token is valid."""
    return token_customer(conn.headers.get(DEVICE_HEADER) or "")


def token_customer(tok: str) -> str | None:
    """The customer a device token belongs to, if it is valid and not expired."""
    parts = tok.rsplit(".", 2)
    if len(parts) != 3:
        return None
    cid, exp, sig = parts
    if not exp.isdigit() or int(exp) <= time.time():
        return None
    return cid if hmac.compare_digest(sig.encode(), _sign(f"device:{cid}:{exp}").encode()) else None


def is_device(conn: Request | WebSocket, customer_id: str) -> bool:
    return device_customer(conn) == customer_id


def require_device(conn: Request | WebSocket) -> str:
    cid = device_customer(conn)
    if cid is None:
        raise HTTPException(401, "This phone isn't signed in to CS Bank. Open the app and sign up again.")
    return cid
