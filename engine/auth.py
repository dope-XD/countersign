"""Who may do what.

Staff: a shared PIN unlocks the agent console, fraud desk, demo panel and metrics. Browsers
exchange it once for a signed HttpOnly cookie; scripts (the IndiaCall simulator, tests) send
it in an `X-Staff-Pin` header. Ten wrong PINs in five minutes from one client lock PIN
checks for that client for five minutes, and 100 from everyone together lock them for all
(cookies already issued keep working). One stranger can't lock the staff out, and nobody
can guess the 8-digit PIN at speed.

Customers: a phone becomes "Rahul's phone" by opening a one-time login link that the demo
operator shows as a QR code on /demo (single use, 10 minutes). That sets a signed cookie for
that customer only. Everything a customer can do (bind a passkey, approve or decline, pay,
check a voice note, receive app events) needs it. The softphone needs nothing: it is the
caller's phone, and the caller may be the attacker.

Devices: the CS Bank Android app's native side (android/) can't see Chrome's cookies, so a
logged-in bank page hands it a device token for that customer (`X-Device-Token`). The token
can only report the phone's call state and receive that customer's app events, so the app
can raise notifications. Approving anything still takes the passkey.
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
LOGIN_TTL = 600.0
_logins: dict[str, tuple[str, float]] = {}  # sha256(token) -> (customer id, expiry)


def customer_cookie_name(customer_id: str) -> str:
    return f"cs_cust_{customer_id}"


def _token_key(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def mint_login(customer_id: str) -> str:
    """A one-time login token for one customer's app (shown as a QR code on /demo)."""
    now = time.time()
    for k in [k for k, (_, exp) in _logins.items() if exp < now]:
        del _logins[k]
    token = secrets.token_urlsafe(18)
    _logins[_token_key(token)] = (customer_id, now + LOGIN_TTL)
    return token


def redeem_login(customer_id: str, token: str) -> bool:
    """True once: the token is consumed even when it was for another customer."""
    entry = _logins.pop(_token_key(token), None) if token else None
    return bool(entry) and entry[0] == customer_id and entry[1] > time.time()


def is_customer(conn: Request | WebSocket, customer_id: str) -> bool:
    """This phone is logged in to `customer_id`'s app. Staff count too (laptop-only fallback,
    the IndiaCall simulator and tests act for customers with the staff PIN)."""
    return cookie_ok(conn.cookies.get(customer_cookie_name(customer_id)), f"customer:{customer_id}") or is_staff(conn)


DEVICE_HEADER = "x-device-token"


def make_device_token(customer_id: str) -> str:
    return make_cookie(f"device:{customer_id}")


def is_device(conn: Request | WebSocket, customer_id: str) -> bool:
    return cookie_ok(conn.headers.get(DEVICE_HEADER), f"device:{customer_id}")


def require_customer(conn: Request | WebSocket, customer_id: str) -> None:
    if not is_customer(conn, customer_id):
        raise HTTPException(401, "This phone isn't logged in to this bank account. Scan the login code on the demo screen.")
