"""Who can act as whom: app-only routes, device tokens, the staff-PIN lockout, and the
after-the-fact check that an approval signed exactly what the customer saw."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from engine import auth
from engine.app import _event_topics, app
from engine.stepup import devicekeys
from ml.eval.soft_device import SoftDevice

PIN = {auth.HEADER: "4321"}


@pytest.fixture()
def staff():
    with TestClient(app, base_url="https://testserver") as c:
        c.headers.update(PIN)
        c.post("/api/demo/reset")
        yield c


def _claimed(staff, cid: str) -> SoftDevice:
    dev = SoftDevice()
    dev.token = staff.post("/api/m/claim", json={"customer_id": cid, "public_key": dev.public_key}).json()["token"]
    return dev


def test_app_routes_need_a_device_token(staff):
    anon = TestClient(app, base_url="https://testserver")
    assert anon.get("/api/m/home").status_code == 401
    assert anon.post("/api/m/pay", json={"payee": "shop@okaxis", "amount": 10}).status_code == 401
    assert anon.get("/api/m/home", headers={auth.DEVICE_HEADER: "rahul.9999999999.forged"}).status_code == 401
    rahul = _claimed(staff, "rahul")
    me = anon.get("/api/m/home", headers={auth.DEVICE_HEADER: rahul.token}).json()
    assert me["account"]["id"] == "rahul"


def test_claiming_a_seeded_account_needs_the_staff_pin(staff):
    anon = TestClient(app, base_url="https://testserver")
    assert anon.post("/api/m/claim", json={"customer_id": "rahul", "public_key": SoftDevice().public_key}).status_code == 401


def test_device_token_cannot_be_moved_to_another_customer(staff):
    rahul = _claimed(staff, "rahul")
    cid, exp, sig = rahul.token.rsplit(".", 2)
    forged = f"sunita.{exp}.{sig}"
    assert auth.device_customer(SimpleNamespace(headers={auth.DEVICE_HEADER: forged})) is None


def test_another_customer_cannot_decide_rahuls_approval(staff):
    a = devicekeys.request_approval("req_x", "rahul", "app_approval", {"action": "Change registered mobile number"})
    sunita = _claimed(staff, "sunita")
    r = staff.post(f"/api/m/approvals/{a['id']}/decide", json={"decision": "decline"}, headers={auth.DEVICE_HEADER: sunita.token})
    assert r.status_code == 403
    assert devicekeys.public_approval(a["id"])["status"] == "pending"


def test_events_socket_only_carries_the_apps_own_customer(staff):
    rahul = _claimed(staff, "rahul")
    phone_conn = SimpleNamespace(cookies={}, headers={auth.DEVICE_HEADER: rahul.token})
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
    rahul = _claimed(staff, "rahul")
    a = devicekeys.request_approval("req_y", "rahul", "app_approval", {"action": "Change registered mobile number", "new": "+917777000111"})
    devicekeys.decide(a["id"], "approve", rahul.sign(a))
    ev = staff.get(f"/api/approvals/{a['id']}/evidence").json()
    assert ev["checks"] == {"challenge_is_hash_of_summary": True, "signature_verifies": True}
