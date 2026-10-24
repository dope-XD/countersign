"""Caller checks: is the person ringing Mom as "Rohan" really Rohan's phone? (engine/callcheck.py)"""

import time

import pytest

from engine import callcheck
from engine.db import db
from engine.hub import hub
from engine.mocks.world import world
from engine.stepup import devicekeys
from engine.tests.test_mobile import Phone, client, family  # noqa: F401  (client is a fixture)


@pytest.fixture()
def fam(client):  # noqa: F811
    mom, son = Phone(client, "Asha Verma"), Phone(client, "Rohan Verma")
    family(mom, son, a_calls_b="Rohan", b_calls_a="Mom")
    return mom, son


@pytest.fixture()
def quick(monkeypatch):
    """Negative verdicts are final at once instead of waiting for late events."""
    monkeypatch.setattr(callcheck, "WAIT_S", 0.0)


def ev(phone, call_id, event, peer=None, elapsed_ms=0, kind="phone"):
    r = phone.post("/api/m/call-event", {"call_id": call_id, "event": event, "kind": kind, "peer": peer, "elapsed_ms": elapsed_ms})
    assert r.status_code == 200, r.text


def check(mom, son, call_id="m1", matched=True, via="auto"):
    r = mom.post("/api/m/checks", {"call_id": call_id, "claimed": son.id, "number_matched": matched, "via": via})
    assert r.status_code == 200, r.text
    return r.json()


def get(mom, c):
    return mom.get(f"/api/m/checks/{c['id']}").json()


# ------------------------------------------------------------------ verdicts
def test_his_phone_calling_mom_is_verified(fam):
    mom, son = fam
    ev(son, "s1", "outgoing", peer=mom.id, elapsed_ms=1500)
    ev(mom, "m1", "ringing", peer=son.id)
    c = check(mom, son)
    assert c["verdict"] == "verified" and c["label"] == "Rohan" and c["decided_at"]
    assert callcheck.scam_for(mom.id) is None


def test_a_new_family_link_only_gives_likely(client):  # noqa: F811
    mom, son = Phone(client, "Asha Verma"), Phone(client, "Rohan Verma")
    family(mom, son, a_calls_b="Rohan", b_calls_a="Mom", old=False)
    ev(son, "s1", "outgoing", peer=mom.id)
    ev(mom, "m1", "ringing", peer=son.id)
    assert check(mom, son)["verdict"] == "likely"


def test_his_phone_dialling_an_unmatched_number_at_that_moment_is_likely(fam):
    mom, son = fam
    ev(son, "s1", "outgoing", peer=None, elapsed_ms=2000)  # his redirection role is off: no number seen
    ev(mom, "m1", "ringing", peer=None)
    assert check(mom, son, matched=False, via="manual")["verdict"] == "likely"


def test_a_call_he_already_hung_up_does_not_count(fam, quick):
    mom, son = fam
    ev(son, "s1", "outgoing", peer=mom.id, elapsed_ms=10_000)
    ev(son, "s1", "ended", elapsed_ms=3_000)  # he hung up; then someone else rings Mom with his number
    ev(mom, "m2", "ringing", peer=son.id)
    c = check(mom, son, call_id="m2")
    assert c["verdict"] == "not_them" and c["spoof_suspected"]


def test_his_phone_on_a_different_call_is_not_with_you(fam, quick):
    mom, son = fam
    ev(son, "s1", "outgoing", peer=None, elapsed_ms=180_000)  # a call he started 3 minutes ago, still going
    ev(mom, "m1", "ringing", peer=son.id)
    c = check(mom, son)
    assert c["verdict"] == "not_with_you"
    assert callcheck.scam_for(mom.id)["reason"] == "not_with_you"


def test_spoofed_number_is_not_them_and_he_is_told(fam, quick):
    mom, son = fam
    son.get("/api/m/home")  # his app is online, and his phone is on no call
    q = hub.subscribe(f"app:{son.id}")
    ev(mom, "m1", "ringing", peer=son.id)  # Mom's phone shows Rohan's saved number
    c = check(mom, son, matched=True)
    assert c["verdict"] == "not_them" and c["spoof_suspected"]
    alerts = []
    while not q.empty():
        alerts.append(q.get_nowait())
    hub.unsubscribe(q)
    assert any('"spoof_alert"' in a and '"label": "Mom"' in a for a in alerts)
    scam = callcheck.scam_for(mom.id)
    assert scam["check_id"] == c["id"] and scam["label"] == "Rohan" and scam["until"] > time.time()
    case = db.query("SELECT * FROM cases WHERE request_id=?", [c["id"]])[0]
    assert case["reasons"][0] == "IMPERSONATION_CALL" and case["tier"] == "RED"


def test_unknown_number_claiming_to_be_him_is_not_them_without_spoof(fam, quick):
    mom, son = fam
    son.get("/api/m/home")
    ev(mom, "m1", "ringing", peer=None)
    c = check(mom, son, matched=False, via="manual")
    assert c["verdict"] == "not_them" and not c["spoof_suspected"]


def test_offline_phone_is_cant_reach_never_not_them(fam, quick):
    mom, son = fam
    world.app_sessions.pop(son.id, None)
    callcheck._last_event.pop(son.id, None)
    ev(mom, "m1", "ringing", peer=son.id)
    c = check(mom, son)
    assert c["verdict"] == "cant_reach"
    assert callcheck.scam_for(mom.id) is None


# ------------------------------------------------------------------ waiting for late events
def test_negative_waits_and_a_late_event_flips_it_to_verified(fam, monkeypatch):
    monkeypatch.setattr(callcheck, "WAIT_S", 5.0)
    mom, son = fam
    son.get("/api/m/home")
    ev(mom, "m1", "ringing", peer=son.id)
    c = check(mom, son)
    assert c["verdict"] == "checking" and c["decided_at"] is None
    ev(son, "s1", "outgoing", peer=mom.id, elapsed_ms=2500)  # his phone's report arrives late
    assert get(mom, c)["verdict"] == "verified"


def test_negative_is_final_at_the_deadline(fam, monkeypatch):
    monkeypatch.setattr(callcheck, "WAIT_S", 0.3)
    mom, son = fam
    son.get("/api/m/home")
    ev(mom, "m1", "ringing", peer=son.id)
    c = check(mom, son)
    assert c["verdict"] == "checking"
    time.sleep(0.5)
    assert get(mom, c)["verdict"] == "not_them"


# ------------------------------------------------------------------ ring him
def _rung(mom, son):
    son.get("/api/m/home")
    ev(mom, "m1", "ringing", peer=son.id)
    c = check(mom, son)
    r = mom.post(f"/api/m/checks/{c['id']}/ring").json()
    assert r["ring"] == "ringing"
    a = [x for x in son.approvals() if x["kind"] == "call_check"][0]
    assert a["question"] == "Is it you on Mom's call?" and a["from"] == "Mom"
    return c, a


def test_ring_yes_with_his_key_confirms_and_lifts_the_scam(fam, quick):
    mom, son = fam
    c, a = _rung(mom, son)
    assert callcheck.scam_for(mom.id) is not None
    assert son.answer(a, "approve").status_code == 200
    c = get(mom, c)
    assert c["ring"] == "yes"
    assert callcheck.scam_for(mom.id) is None


def test_ring_no_marks_the_call_a_scam(fam, quick):
    mom, son = fam
    c, a = _rung(mom, son)
    mom.post("/api/m/scam/dismiss")
    son.answer(a, "decline")
    assert get(mom, c)["ring"] == "no"
    assert callcheck.scam_for(mom.id)["reason"] == "ring_no"
    case = db.query("SELECT * FROM cases WHERE request_id=?", [c["id"]])[0]
    assert any(e["event"] == "call_check_ring_no" for e in case["timeline"])


def test_unanswered_ring_becomes_no_answer(fam, quick, monkeypatch):
    mom, son = fam
    c, _ = _rung(mom, son)
    monkeypatch.setattr(devicekeys, "APPROVAL_TTL", -1)
    assert get(mom, c)["ring"] == "no_answer"


def test_another_phone_cannot_say_yes_for_him(fam, quick, client):  # noqa: F811
    mom, son = fam
    _, a = _rung(mom, son)
    thief = Phone(client, "Some One")
    assert thief.answer(a, "approve").status_code == 403


# ------------------------------------------------------------------ scam context, privacy, expiry
def test_scam_lasts_ten_minutes_after_the_call_and_can_be_dismissed(fam, quick, monkeypatch):
    mom, son = fam
    son.get("/api/m/home")
    ev(mom, "m1", "ringing", peer=son.id)
    check(mom, son)
    ev(mom, "m1", "ended", elapsed_ms=0)
    assert callcheck.scam_for(mom.id) is not None
    monkeypatch.setattr(callcheck, "SCAM_AFTER_END_S", -1.0)
    assert callcheck.scam_for(mom.id) is None


def test_dismiss_turns_the_pay_guard_off(fam, quick):
    mom, son = fam
    son.get("/api/m/home")
    ev(mom, "m1", "ringing", peer=son.id)
    check(mom, son)
    assert mom.post("/api/m/scam/dismiss").json() == {"scam": None}
    assert callcheck.scam_for(mom.id) is None


def test_raw_numbers_and_strangers_are_rejected(fam):
    mom, son = fam
    for peer in ("+919812345678", "9812345678", "98123 45678"):
        r = mom.post("/api/m/call-event", {"call_id": "m1", "event": "ringing", "peer": peer})
        assert r.status_code == 422, peer
    assert mom.post("/api/m/call-event", {"call_id": "m1", "event": "ringing", "peer": "c_notfamily"}).status_code == 422
    assert mom.post("/api/m/checks", {"call_id": "m1", "claimed": "c_notfamily"}).status_code == 404
    assert mom.get("/api/m/checks/chk_nope").status_code == 404


def test_someone_elses_check_is_private(fam, client):  # noqa: F811
    mom, son = fam
    ev(son, "s1", "outgoing", peer=mom.id)
    c = check(mom, son)
    assert son.get(f"/api/m/checks/{c['id']}").status_code == 404
    assert [x["id"] for x in mom.get("/api/m/checks").json()] == [c["id"]]
    assert son.get("/api/m/checks").json() == []


def test_events_expire(fam, monkeypatch):
    mom, son = fam
    ev(son, "s1", "outgoing", peer=mom.id, elapsed_ms=120_000)
    monkeypatch.setattr(callcheck, "EVENT_TTL", 60.0)
    callcheck.prune()
    assert not callcheck._events[son.id]


# ------------------------------------------------------------------ the call listener's scam alert
def alert(phone, call_id="m1", **kw):
    body = {
        "call_id": call_id,
        "level": "scam",
        "type": "digital_arrest",
        "cues": ["authority", "threat", "secrecy", "money_ask"],
        "sources": ["cues", "phone_ai"],
    } | kw
    return phone.post("/api/m/scam-alert", body)


def test_scam_alert_turns_on_the_pay_guard_and_opens_a_case(fam):
    mom, _ = fam
    r = alert(mom)
    assert r.status_code == 200, r.text
    assert r.json()["scam"]["reason"] == "listener:digital_arrest"
    assert mom.get("/api/m/home").json()["scam"]["reason"] == "listener:digital_arrest"
    case = db.query("SELECT * FROM cases WHERE customer_id=? AND status='open'", [mom.id])[0]
    assert case["reasons"][:2] == ["SCAM_CALL", "DIGITAL_ARREST"] and case["tier"] == "RED"


def test_scam_alert_rings_the_family_once_per_call(fam):
    mom, son = fam
    son.get("/api/m/home")  # his app is online
    q = hub.subscribe(f"app:{son.id}")
    first = alert(mom).json()
    assert first["alarmed"] == [son.id] and first["text_these"] == []
    again = alert(mom).json()
    assert again["alarmed"] == [] and again["text_these"] == []
    msgs = []
    while not q.empty():
        msgs.append(q.get_nowait())
    hub.unsubscribe(q)
    alarms = [m for m in msgs if '"family_alarm"' in m]
    assert len(alarms) == 1 and '"label": "Mom"' in alarms[0] and '"scam_type": "digital_arrest"' in alarms[0]
    assert alert(mom, call_id="m2").json()["alarmed"] == [son.id]  # a new call alarms again


def test_offline_family_come_back_to_be_texted(fam):
    mom, son = fam
    world.app_sessions.pop(son.id, None)
    callcheck._last_event.pop(son.id, None)
    r = alert(mom).json()
    assert r["alarmed"] == [] and r["text_these"] == [son.id]


def test_scam_alert_takes_ids_never_words(fam):
    mom, _ = fam
    assert alert(mom, cues=["he said send the money"]).status_code == 422
    assert alert(mom, level="warn").status_code == 422
    assert alert(mom, type="something_else").status_code == 422
    assert alert(mom, sources=["the internet"]).status_code == 422


def test_a_caller_check_scam_keeps_its_reason(fam, quick):
    mom, son = fam
    son.get("/api/m/home")
    ev(mom, "m1", "ringing", peer=son.id)
    check(mom, son)  # not_them
    assert alert(mom).json()["scam"]["reason"] == "not_them"


def clear(phone, call_id="m1", **kw):
    body = {"call_id": call_id, "reason": "know_caller", "level": "scam", "type": "digital_arrest", "cues": ["authority", "threat"]} | kw
    return phone.post("/api/m/scam-alert/clear", body)


def test_not_a_scam_turns_off_the_pay_guard_and_tells_the_family(fam):
    mom, son = fam
    son.get("/api/m/home")
    alert(mom)
    q = hub.subscribe(f"app:{son.id}")
    r = clear(mom)
    assert r.status_code == 200, r.text
    assert r.json()["scam"] is None and r.json()["cleared"] == [son.id]
    assert mom.get("/api/m/home").json()["scam"] is None
    msgs = []
    while not q.empty():
        msgs.append(q.get_nowait())
    hub.unsubscribe(q)
    cleared = [m for m in msgs if '"family_alarm_cleared"' in m]
    assert len(cleared) == 1 and '"label": "Mom"' in cleared[0] and '"reason": "know_caller"' in cleared[0]


def test_not_a_scam_keeps_one_ids_only_record_and_silences_the_call(fam):
    mom, son = fam
    son.get("/api/m/home")
    n = len(callcheck.false_alarms)
    clear(mom, call_id="w1", level="warn", type="bank_kyc")  # a warn: nobody was alarmed yet
    assert len(callcheck.false_alarms) == n + 1
    rec = callcheck.false_alarms[-1]
    assert rec["reason"] == "know_caller" and rec["type"] == "bank_kyc" and set(rec) == {"at", "call_id", "reason", "level", "type", "cues", "sources"}
    assert alert(mom, call_id="w1").json()["alarmed"] == []  # a later alert on the same call stays quiet
    assert clear(mom, cues=["he said the bank"]).status_code == 422


def test_listener_settings_round_trip(fam):
    mom, _ = fam
    me = mom.post("/api/m/prefs", {"listen_calls": False, "sms_fallback": False}).json()
    assert me["listen_calls"] is False and me["sms_fallback"] is False
    assert mom.get("/api/m/home").json()["me"]["listen_calls"] is False
