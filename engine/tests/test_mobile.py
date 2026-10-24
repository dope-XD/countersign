"""The app's API: sign-up, family, home and settings (docs/agents/CONTRACT.md). Edge-case ids (F7...) refer to docs/EDGE_CASES.md."""

import time

import pytest
from fastapi.testclient import TestClient

from engine import auth, callcheck, mobile
from engine.app import app
from engine.mocks.world import world
from ml.eval.soft_device import SoftDevice

PIN = {auth.HEADER: "4321"}
_n = iter(range(10**6))


@pytest.fixture()
def client():
    with TestClient(app, base_url="https://testserver") as c:
        c.headers.update(PIN)
        c.post("/api/demo/reset")
        mobile._signups.clear()  # every test signs up several phones from the same test address
        yield c


class Phone:
    """One judge's phone: a software key plus the device token the server issued."""

    def __init__(self, client: TestClient, name: str, share: bool = True, channel: str = "ring"):
        self.c = client
        self.dev = SoftDevice()
        mobile = f"+9198{next(_n) + int(time.time()) % 10**6:08d}"
        r = client.post(
            "/api/m/signup",
            json={"name": name, "mobile": mobile, "check_channel": channel, "share_call_status": share, "public_key": self.dev.public_key},
        )
        assert r.status_code == 200, r.text
        self.token = r.json()["token"]
        self.id = r.json()["me"]["id"]

    def h(self):
        return {auth.DEVICE_HEADER: self.token}

    def get(self, path):
        return self.c.get(path, headers=self.h())

    def post(self, path, json=None):
        return self.c.post(path, json=json, headers=self.h())

    def approvals(self):
        return self.get("/api/m/home").json()["approvals"]

    def answer(self, approval, decision):
        body = {"decision": decision, "signature": self.dev.sign(approval) if decision == "approve" else None}
        return self.post(f"/api/m/approvals/{approval['id']}/decide", body)


def family(a: Phone, b: Phone, a_calls_b: str, b_calls_a: str, old: bool = True):
    """b joins a's family. `old` back-dates the link past the 24 h rule (F7)."""
    code = a.post("/api/m/family/invite").json()["code"]
    assert b.post("/api/m/family/join", {"code": code, "label": b_calls_a}).status_code == 200
    assert a.post("/api/m/family/confirm", {"customer_id": b.id, "label": a_calls_b}).status_code == 200
    if old:
        for x, y in ((a, b), (b, a)):
            world.customer(x.id).family[y.id]["since"] = 0.0


@pytest.fixture()
def mom_and_son(client):
    mom, son = Phone(client, "Asha Verma"), Phone(client, "Rohan Verma")
    family(mom, son, a_calls_b="Rohan", b_calls_a="Mom")
    return mom, son


# ------------------------------------------------------------------ sign-up and family
def test_signup_gives_an_account_and_a_token(client):
    p = Phone(client, "Meera Iyer")
    home = p.get("/api/m/home").json()
    assert set(home) == {"me", "family", "join_requests", "approvals", "checks", "scam"}
    assert home["me"]["name"] == "Meera Iyer" and home["me"]["lang"] == "en" and home["me"]["check_channel"] == "ring"
    assert home["family"] == [] and home["checks"] == [] and home["scam"] is None


def test_signup_checks_the_mobile_number(client):
    dev = SoftDevice()
    bad = client.post("/api/m/signup", json={"name": "X Y", "mobile": "12345", "public_key": dev.public_key})
    assert bad.status_code == 422
    taken = client.post("/api/m/signup", json={"name": "X Y", "mobile": "+919845012210", "public_key": dev.public_key})
    assert taken.status_code == 409  # Rahul's number


def test_signups_are_rate_limited_per_client(client):
    for _ in range(mobile.SIGNUPS_PER_CLIENT):
        Phone(client, "Some One")
    dev = SoftDevice()
    r = client.post("/api/m/signup", json={"name": "Some One", "mobile": "+919812300099", "public_key": dev.public_key})
    assert r.status_code == 429


def test_family_needs_both_phones(client):
    a, b = Phone(client, "Asha Verma"), Phone(client, "Rohan Verma")
    code = a.post("/api/m/family/invite").json()["code"]
    b.post("/api/m/family/join", {"code": code, "label": "Mom"})
    assert world.customer(a.id).family == {}  # nothing linked until the inviter confirms (F7)
    assert a.get("/api/m/home").json()["join_requests"][0]["customer_id"] == b.id
    a.post("/api/m/family/confirm", {"customer_id": b.id, "label": "Rohan"})
    assert [f["label"] for f in a.get("/api/m/home").json()["family"]] == ["Rohan"]
    assert [f["label"] for f in b.get("/api/m/home").json()["family"]] == ["Mom"]
    assert b.post("/api/m/family/join", {"code": "000000", "label": "x"}).status_code == 404


def test_accounts_survive_a_demo_reset(client, mom_and_son):
    mom, _ = mom_and_son
    client.post("/api/demo/reset")
    assert mom.get("/api/m/home").json()["family"][0]["label"] == "Rohan"


def test_home_shows_who_is_online_and_new_links(client):
    a, b = Phone(client, "Asha Verma"), Phone(client, "Rohan Verma")
    family(a, b, a_calls_b="Rohan", b_calls_a="Mom", old=False)
    rohan = a.get("/api/m/home").json()["family"][0]
    assert rohan["label"] == "Rohan" and rohan["online"] and rohan["new_link"]
    assert "upi_id" not in rohan
    world.app_sessions.pop(b.id)
    callcheck._last_event.pop(b.id, None)
    assert not a.get("/api/m/home").json()["family"][0]["online"]


def test_language_is_chosen_at_signup_and_changed_in_settings(client):
    dev = SoftDevice()
    r = client.post("/api/m/signup", json={"name": "Kamla Devi", "mobile": "+919812300123", "lang": "hi", "public_key": dev.public_key})
    assert r.json()["me"]["lang"] == "hi"
    h = {auth.DEVICE_HEADER: r.json()["token"]}
    me = client.post("/api/m/prefs", json={"lang": "en", "check_channel": "notify"}, headers=h).json()
    assert me["lang"] == "en" and me["check_channel"] == "notify"
    assert client.post("/api/m/prefs", json={"lang": "fr"}, headers=h).status_code == 422


def test_emulator_numbers_only_on_the_dev_server(client, monkeypatch):
    dev = SoftDevice()
    body = {"name": "Emu Mom", "mobile": "5555215554", "public_key": dev.public_key}
    assert client.post("/api/m/signup", json=body).status_code == 422
    monkeypatch.setattr(mobile, "ALLOW_TEST_NUMBERS", True)
    r = client.post("/api/m/signup", json=body)
    assert r.status_code == 200 and r.json()["me"]["mobile"] == "+15555215554"


def test_the_old_bank_routes_are_gone(client):
    p = Phone(client, "Meera Iyer")
    gone = (404, 405)  # 405: the web app's catch-all page route still answers GET
    assert p.post("/api/m/pay", {"payee": "shop@okaxis", "amount": 10}).status_code in gone
    assert p.post("/api/m/kill-switch").status_code in gone
    assert p.post("/api/m/call-state", {"state": "active"}).status_code in gone
