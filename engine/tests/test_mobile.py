"""The CS Bank app's API: sign-up, family, the payment guard and family check, holds, the kill
switch. Edge-case ids (F1, F2...) refer to docs/EDGE_CASES.md."""

import time

import pytest
from fastapi.testclient import TestClient

from engine import auth, guard, mobile
from engine.app import app
from engine.db import db
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
        self.id = r.json()["account"]["id"]
        self.upi = r.json()["account"]["upi_id"]

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

    def on_call(self, kind="phone", direction="incoming"):
        assert self.post("/api/m/call-state", {"state": "active", "kind": kind, "direction": direction}).status_code == 200


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


def paused_payment(mom: Phone, amount=50_000, payee="quickhelp.new@okaxis"):
    mom.on_call()
    p = mom.post("/api/m/pay", {"payee": payee, "amount": amount}).json()
    assert p["status"] == "paused", p
    return p


# ------------------------------------------------------------------ sign-up and family
def test_signup_gives_an_account_and_a_token(client):
    p = Phone(client, "Meera Iyer")
    home = p.get("/api/m/home").json()
    assert home["account"]["balance"] == 250_000 and home["account"]["upi_id"].endswith("@csbank")
    assert home["account"]["check_channel"] == "ring" and home["family"] == []


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


# ------------------------------------------------------------------ when the guard fires (F12, F8)
def test_guard_pauses_only_when_a_call_is_involved(client, mom_and_son):
    mom, _ = mom_and_son
    no_call = mom.post("/api/m/pay", {"payee": "stranger@okaxis", "amount": 50_000}).json()
    assert no_call["status"] == "confirm"  # F8: "did someone ask you for this?"
    small = mom.post("/api/m/pay", {"payee": "stranger@okaxis", "amount": 900}).json()
    assert small["status"] == "executed"
    mom.on_call()
    on_call = mom.post("/api/m/pay", {"payee": "stranger@okaxis", "amount": 50_000}).json()
    assert on_call["status"] == "paused" and on_call["guard"]["reasons"][0] == "You're on a call right now"
    known = mom.post("/api/m/pay", {"payee": "bses.electricity@okhdfc", "amount": 50_000}).json()
    assert known["status"] == "executed"  # known payees never pause


def test_someone_asked_by_message_starts_the_family_check(client, mom_and_son):
    mom, _ = mom_and_son
    p = mom.post("/api/m/pay", {"payee": "stranger@okaxis", "amount": 50_000}).json()
    p = mom.post(f"/api/m/payments/{p['id']}/asked", {"someone_asked": True}).json()
    assert p["status"] == "paused" and p["guard"]["reasons"][0] == "Someone asked you for this money"


def test_internet_call_adds_the_digital_arrest_tip(client, mom_and_son):
    mom, _ = mom_and_son
    mom.on_call(kind="internet")
    p = mom.post("/api/m/pay", {"payee": "cbi.officer@okaxis", "amount": 90_000}).json()
    assert p["status"] == "paused" and "never ask for money" in p["guard"]["tips"][0]  # F9


def test_kill_switch_blocks_payments(client, mom_and_son):
    mom, _ = mom_and_son
    assert mom.post("/api/m/kill-switch").json()["kill_switch"]
    assert mom.post("/api/m/pay", {"payee": "bses.electricity@okhdfc", "amount": 100}).status_code == 423


# ------------------------------------------------------------------ the family check
def test_son_says_no_and_the_payment_stops(client, mom_and_son):
    mom, son = mom_and_son
    before = world.customer(mom.id).balance
    p = paused_payment(mom)
    p = mom.post(f"/api/m/payments/{p['id']}/ask/{son.id}").json()
    assert p["status"] == "awaiting_family"
    apr = son.approvals()[0]
    assert apr["summary"]["question"] == "Did you ask Mom for ₹50,000?"  # in the son's own words
    assert "phone call" in apr["summary"]["detail"] and apr["deliver"] == "ring"
    son.answer(apr, "decline")
    p = mom.get(f"/api/m/payments/{p['id']}").json()
    assert p["status"] == "cancelled" and p["case_id"] and p["report"]["helpline"] == "1930"
    assert db.get("reports", p["report"]["id"])["case_id"] == p["case_id"]
    assert world.customer(mom.id).balance == before


def test_son_says_yes_with_his_fingerprint(client, mom_and_son):
    mom, son = mom_and_son
    p = paused_payment(mom)
    mom.post(f"/api/m/payments/{p['id']}/ask/{son.id}")
    apr = son.approvals()[0]
    assert son.post(f"/api/m/approvals/{apr['id']}/decide", {"decision": "approve"}).status_code == 400  # no signature
    stranger = SoftDevice()
    bad = son.post(f"/api/m/approvals/{apr['id']}/decide", {"decision": "approve", "signature": stranger.sign(apr)})
    assert bad.status_code == 400  # F6: another phone's key
    assert son.answer(apr, "approve").status_code == 200
    assert mom.get(f"/api/m/payments/{p['id']}").json()["status"] == "executed"


def test_new_family_link_can_stop_but_not_release_at_once(client):
    mom, son = Phone(client, "Asha Verma"), Phone(client, "Rohan Verma")
    family(mom, son, "Rohan", "Mom", old=False)
    p = paused_payment(mom)
    mom.post(f"/api/m/payments/{p['id']}/ask/{son.id}")
    son.answer(son.approvals()[0], "approve")
    p = mom.get(f"/api/m/payments/{p['id']}").json()
    assert p["status"] == "held" and p["hold_until"] > time.time() + 3000  # F7: goes out after the golden hour


def test_call_status_shown_only_during_a_check_and_only_if_shared(client):
    mom, son, aunt = Phone(client, "Asha Verma"), Phone(client, "Rohan Verma"), Phone(client, "Lata Verma", share=False)
    family(mom, son, "Rohan", "Mom")
    family(mom, aunt, "Lata", "Asha")
    p = paused_payment(mom)
    assert all("status" not in f for f in p["family"])  # nobody asked yet: nothing shown (F10)
    p = mom.post(f"/api/m/payments/{p['id']}/ask-all").json()
    st = {f["label"]: f.get("status") for f in p["family"]}
    assert st["Rohan"]["shared"] is True and st["Rohan"]["on_call"] is False
    assert st["Lata"] == {"shared": False}
    son.on_call()
    st = {f["label"]: f.get("status") for f in mom.get(f"/api/m/payments/{p['id']}").json()["family"]}
    assert st["Rohan"]["on_call"] is True


def test_ask_all_one_no_stops_it(client):
    mom, son, aunt = Phone(client, "Asha Verma"), Phone(client, "Rohan Verma"), Phone(client, "Lata Verma")
    family(mom, son, "Rohan", "Mom")
    family(mom, aunt, "Lata", "Asha")
    p = paused_payment(mom)
    mom.post(f"/api/m/payments/{p['id']}/ask-all")
    assert son.approvals() and aunt.approvals()
    aunt.answer(aunt.approvals()[0], "decline")
    assert mom.get(f"/api/m/payments/{p['id']}").json()["status"] == "cancelled"


def test_no_answer_moves_the_payment_on(client, mom_and_son):
    mom, son = mom_and_son
    p = paused_payment(mom)
    mom.post(f"/api/m/payments/{p['id']}/ask/{son.id}")
    row = db.get("requests", p["id"])
    d = row["details"]
    d["asked"][0]["at"] -= guard.ANSWER_WAIT_S + 1
    db.update("requests", p["id"], {"details": d})
    guard.tick()
    p = mom.get(f"/api/m/payments/{p['id']}").json()
    assert p["status"] == "paused" and p["no_answer"]  # F2: back to the options, not stuck
    son.answer(son.approvals()[0], "decline")  # a late "No" still stops it
    assert mom.get(f"/api/m/payments/{p['id']}").json()["status"] == "cancelled"


# ------------------------------------------------------------------ F1: "his phone is broken"
def test_send_to_his_own_account_instead(client, mom_and_son):
    mom, son = mom_and_son
    m0, s0 = world.customer(mom.id).balance, world.customer(son.id).balance
    p = paused_payment(mom)
    p = mom.post(f"/api/m/payments/{p['id']}/redirect/{son.id}").json()
    assert p["status"] == "executed" and p["redirected_to"]["upi_id"] == son.upi
    assert world.customer(mom.id).balance == m0 - 50_000 and world.customer(son.id).balance == s0 + 50_000


def test_golden_hour_hold_can_be_cancelled(client, mom_and_son):
    mom, _ = mom_and_son
    m0 = world.customer(mom.id).balance
    p = paused_payment(mom)
    p = mom.post(f"/api/m/payments/{p['id']}/hold").json()
    assert p["status"] == "held" and world.customer(mom.id).balance == m0 - 50_000  # provisional debit
    p = mom.post(f"/api/m/payments/{p['id']}/cancel").json()
    assert p["status"] == "cancelled" and world.customer(mom.id).balance == m0


def test_golden_hour_hold_is_released_after_the_hour(client, mom_and_son):
    mom, son = mom_and_son
    s0 = world.customer(son.id).balance
    p = paused_payment(mom, payee=son.upi.replace("@", ".x@"))  # some new payee
    p = mom.post(f"/api/m/payments/{p['id']}/hold").json()
    row = db.get("requests", p["id"])
    db.update("requests", p["id"], {"details": {**row["details"], "hold_until": time.time() - 1}})
    guard.tick()
    assert mom.get(f"/api/m/payments/{p['id']}").json()["status"] == "executed"
    assert world.customer(son.id).balance == s0  # it went to the payee, not the son


def test_small_amount_sends_now_without_a_hold(client, mom_and_son):
    mom, _ = mom_and_son
    world.customer(mom.id).usual_upi_max = 1_000
    p = paused_payment(mom, amount=5_000)
    assert mom.post(f"/api/m/payments/{p['id']}/hold").json()["status"] == "executed"


def test_someone_elses_payment_is_off_limits(client, mom_and_son):
    mom, son = mom_and_son
    p = paused_payment(mom)
    assert son.post(f"/api/m/payments/{p['id']}/cancel").status_code == 403


# ------------------------------------------------------------------ kill switch
def test_kill_switch_off_needs_a_fingerprint_then_an_hour(client, mom_and_son):
    mom, _ = mom_and_son
    mom.post("/api/m/kill-switch")
    apr = mom.post("/api/m/kill-switch/off").json()
    assert apr["kind"] == "kill_switch_off"
    mom.answer(apr, "approve")
    ks = world.customer(mom.id).kill_switch
    assert ks["off_at"] > time.time() + 3000
    ks["off_at"] = time.time() - 1
    guard.tick()
    assert world.customer(mom.id).kill_switch is None


def test_kill_switch_stops_account_changes_on_a_call(client, mom_and_son):
    mom, _ = mom_and_son
    mom.post("/api/m/kill-switch")
    cli = world.customer(mom.id).registered_mobile.replace("+", "%2B")
    with client.websocket_connect(f"/ws/caller?cli={cli}&lang=en") as ws:
        call_id = ws.receive_json()["id"]
        client.post(f"/api/calls/{call_id}/answer")
        r = client.post(f"/api/calls/{call_id}/request", json={"action": "change_mobile", "details": {"new_mobile": "+917777000111"}})
        assert r.status_code == 409 and "kill switch" in r.json()["error"]
        assert client.post(f"/api/calls/{call_id}/request", json={"action": "block_card"}).status_code == 200  # protective: allowed
