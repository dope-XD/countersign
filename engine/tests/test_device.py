"""The CS Bank Android app's native side: a device token from the logged-in bank page, call
state reported by the phone, app events for notifications, and the asset links Chrome checks."""

import dataclasses

import pytest
from fastapi.testclient import TestClient

from engine import app as app_module
from engine import auth
from engine.app import app
from engine.mocks.world import world

PIN = {auth.HEADER: "4321"}


@pytest.fixture()
def staff():
    with TestClient(app, base_url="https://testserver") as c:
        c.headers.update(PIN)
        c.post("/api/demo/reset")
        yield c


def _device(staff, cid: str) -> dict:
    """The header the app's native side sends, got the way the app gets it: from a logged-in page."""
    path = staff.post(f"/api/demo/login-link/{cid}").json()["path"]
    page = TestClient(app, base_url="https://testserver")
    assert page.post(f"/api/app/{cid}/login", json={"token": path.split("#login=", 1)[1]}).status_code == 200
    r = page.post(f"/api/app/{cid}/device")
    assert r.status_code == 200, r.text
    return {auth.DEVICE_HEADER: r.json()["token"]}


def test_only_a_logged_in_page_gets_a_device_token(staff):
    anon = TestClient(app, base_url="https://testserver")
    assert anon.post("/api/app/sunita/device").status_code == 401
    assert anon.post("/api/app/sunita/call-state", json={"state": "active"}).status_code == 401
    dev = _device(staff, "sunita")
    # Sunita's token says nothing about Rahul's phone
    assert anon.post("/api/app/rahul/call-state", json={"state": "active"}, headers=dev).status_code == 401
    # and it is not a login: the bank pages still want the cookie
    assert anon.get("/api/app/sunita/home", headers=dev).status_code == 401


def test_a_live_internet_call_pauses_a_new_payee_payment(staff):
    dev = _device(staff, "sunita")
    anon = TestClient(app, base_url="https://testserver")
    assert anon.post("/api/app/sunita/call-state", json={"state": "active", "kind": "internet"}, headers=dev).status_code == 200
    assert world.on_call["sunita"] == "internet"

    pay = staff.post("/api/app/sunita/pay", json={"payee": "quickhelp.relief@okaxis", "amount": 50000}).json()
    assert pay["status"] == "paused"
    assert any("internet call" in r for r in pay["guard"]["reasons"])

    anon.post("/api/app/sunita/call-state", json={"state": "ended", "kind": "internet"}, headers=dev)
    assert "sunita" not in world.on_call and "sunita" in world.recent_calls  # the 10-minute window starts now
    pay = staff.post("/api/app/sunita/pay", json={"payee": "quickhelp2.relief@okaxis", "amount": 50000}).json()
    assert pay["status"] == "paused" and any("on a call" in r for r in pay["guard"]["reasons"])


def test_device_token_receives_only_its_customers_app_events(staff):
    from types import SimpleNamespace

    from engine.app import _event_topics

    conn = SimpleNamespace(cookies={}, headers=_device(staff, "rahul"))
    assert _event_topics(conn, "app:rahul,app:sunita,desk,calls") == ["app:rahul"]


def test_the_apps_event_stream_carries_approval_requests(staff):
    """What CallWatchService does: open /ws/events with only the device token, get the approval, notify."""
    from engine.stepup import passkeys

    dev = _device(staff, "rahul")
    with TestClient(app, base_url="https://testserver") as phone, phone.websocket_connect("/ws/events?topics=app:rahul,desk", headers=dev) as ws:
        ws.send_text("hb")
        a = passkeys.request_approval("req_dev", "rahul", "app_approval", {"question": "Did you ask us to: Add a new payee?"})
        e = ws.receive_json()
        assert e["topic"] == "app:rahul" and e["type"] == "approval"
        assert e["approval"]["id"] == a["id"] and e["approval"]["summary"]["question"].startswith("Did you ask us")


def test_assetlinks_publish_the_app_only_when_configured(staff, monkeypatch):
    assert staff.get("/.well-known/assetlinks.json").json() == []
    fp = "AB:CD:" + "00:" * 29 + "EF"
    monkeypatch.setattr(app_module, "settings", dataclasses.replace(app_module.settings, android_cert_sha256=fp.lower()))
    (link,) = staff.get("/.well-known/assetlinks.json").json()
    assert link["target"] == {"namespace": "android_app", "package_name": "app.countersign.bank", "sha256_cert_fingerprints": [fp]}
    assert "delegate_permission/common.get_login_creds" in link["relation"]
