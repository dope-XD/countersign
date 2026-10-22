"""Who can act as whom: one-time phone login, customer-only routes, the staff-PIN lockout,
and the after-the-fact check that an approval signed exactly what the customer saw."""

import json

import pytest
from fastapi.testclient import TestClient

from engine import auth
from engine.app import app
from engine.stepup import passkeys
from ml.eval.soft_authenticator import SoftAuthenticator

PIN = {auth.HEADER: "4321"}


@pytest.fixture()
def staff():
    with TestClient(app, base_url="https://testserver") as c:
        c.headers.update(PIN)
        c.post("/api/demo/reset")
        yield c


def _phone(staff, cid: str) -> TestClient:
    """A phone (no staff PIN) logged in to `cid` with a fresh one-time code."""
    path = staff.post(f"/api/demo/login-link/{cid}").json()["path"]
    token = path.split("#login=", 1)[1]
    c = TestClient(app, base_url="https://testserver")
    r = c.post(f"/api/app/{cid}/login", json={"token": token})
    assert r.status_code == 200, r.text
    return c


def test_customer_routes_need_a_logged_in_phone(staff):
    anon = TestClient(app, base_url="https://testserver")
    assert anon.get("/api/app/rahul/home").status_code == 401
    assert anon.post("/api/app/rahul/passkey/options").status_code == 401
    assert anon.post("/api/app/rahul/pay", json={"payee": "x@okaxis", "amount": 10}).status_code == 401
    assert anon.post("/api/app/rahul/voice-note", files={"file": ("n.ogg", b"x")}).status_code == 401


def test_login_code_works_once_and_only_for_its_customer(staff):
    path = staff.post("/api/demo/login-link/rahul").json()["path"]
    token = path.split("#login=", 1)[1]
    phone = TestClient(app, base_url="https://testserver")
    assert phone.post("/api/app/sunita/login", json={"token": token}).status_code == 401  # wrong customer burns it
    assert phone.post("/api/app/rahul/login", json={"token": token}).status_code == 401  # already used

    rahul = _phone(staff, "rahul")
    assert rahul.get("/api/app/rahul/home").status_code == 200
    assert rahul.get("/api/app/sunita/home").status_code == 401  # logged in as Rahul, not Sunita


def test_expired_login_code_is_refused(staff, monkeypatch):
    path = staff.post("/api/demo/login-link/rahul").json()["path"]
    token = path.split("#login=", 1)[1]
    monkeypatch.setattr(auth, "LOGIN_TTL", 0)
    key = auth._token_key(token)
    cid, _ = auth._logins[key]
    auth._logins[key] = (cid, 0.0)
    phone = TestClient(app, base_url="https://testserver")
    assert phone.post("/api/app/rahul/login", json={"token": token}).status_code == 401


def test_another_customer_cannot_decide_rahuls_approval(staff):
    a = passkeys.request_approval("req_x", "rahul", "app_approval", {"action": "Change registered mobile number"})
    sunita = _phone(staff, "sunita")
    r = sunita.post(f"/api/approvals/{a['id']}/decide", json={"decision": "decline"})
    assert r.status_code == 401
    assert passkeys.public_approval(a["id"])["status"] == "pending"


def test_logged_in_phone_binds_a_passkey(staff):
    staff.delete("/api/app/rahul/passkeys")
    rahul = _phone(staff, "rahul")
    soft = SoftAuthenticator("testserver", "https://testserver")
    opts = rahul.post("/api/app/rahul/passkey/options").json()
    r = rahul.post("/api/app/rahul/passkey/verify", json={"credential": soft.register(opts), "device": "test phone"})
    assert r.status_code == 200, r.text


def test_events_socket_only_carries_the_logged_in_customer(staff):
    from types import SimpleNamespace

    from engine.app import _event_topics

    rahul = _phone(staff, "rahul")
    phone_conn = SimpleNamespace(cookies=dict(rahul.cookies), headers={})
    assert _event_topics(phone_conn, "app:rahul,app:sunita,desk,calls") == ["app:rahul"]
    anon_conn = SimpleNamespace(cookies={}, headers={})
    assert _event_topics(anon_conn, "app:rahul,desk") == []
    staff_conn = SimpleNamespace(cookies={}, headers=PIN)
    assert _event_topics(staff_conn, "desk,app:rahul") == ["desk", "app:rahul"]


def test_wrong_pins_lock_pin_checks(staff):
    anon = TestClient(app, base_url="https://testserver")
    for i in range(auth.MAX_FAILS):
        assert anon.get("/api/calls", headers={auth.HEADER: f"{i:08d}"}).status_code == 401
    # locked: even the right PIN is refused until the lockout ends
    assert anon.get("/api/calls", headers=PIN).status_code == 401
    assert anon.post("/api/staff/login", json={"pin": "0000"}).status_code == 429
    auth.reset_pin_lockout()
    assert anon.get("/api/calls", headers=PIN).status_code == 200


def test_one_client_cannot_lock_out_the_others(staff):
    stranger = {"x-forwarded-for": "203.0.113.9"}
    for i in range(auth.MAX_FAILS):
        staff.get("/api/calls", headers={**stranger, auth.HEADER: f"{i:08d}"})
    assert staff.get("/api/calls", headers={**stranger, **PIN}).status_code == 401
    # a spoofed first hop doesn't escape: the proxy's entry (the last one) is what counts
    assert staff.get("/api/calls", headers={"x-forwarded-for": "10.9.9.9, 203.0.113.9", **PIN}).status_code == 401
    assert staff.get("/api/calls", headers={"x-forwarded-for": "198.51.100.4", **PIN}).status_code == 200


def test_wrong_pins_from_everyone_lock_pin_checks_for_all(staff):
    for i in range(auth.MAX_FAILS_ALL):
        staff.get("/api/calls", headers={"x-forwarded-for": f"203.0.{i // 250}.{i % 250}", auth.HEADER: f"{i:08d}"})
    assert staff.get("/api/calls", headers={"x-forwarded-for": "198.51.100.4", **PIN}).status_code == 401


def test_approval_binding_can_be_rechecked(staff):
    staff.delete("/api/app/rahul/passkeys")
    soft = SoftAuthenticator("testserver", "https://testserver")
    opts = json.loads(passkeys.registration_options("rahul", "testserver"))
    passkeys.verify_registration("rahul", soft.register(opts), "test phone", "testserver")
    a = passkeys.request_approval("req_y", "rahul", "app_approval", {"action": "Change registered mobile number", "new": "+917777000111"})
    cred = soft.assert_(json.loads(passkeys.assertion_options(a["id"], "testserver")), b"rahul")
    passkeys.decide(a["id"], "approve", cred, "testserver")

    ev = staff.get(f"/api/approvals/{a['id']}/evidence").json()
    assert ev["checks"] == {"challenge_is_hash_of_summary": True, "signed_challenge_matches": True, "signature_verifies": True}
