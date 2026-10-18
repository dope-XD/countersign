import time

import numpy as np
import pytest

from engine import cases, guard, policy
from engine.audio.codec import mulaw_decode, mulaw_encode, phone_line
from engine.audio.ring import RingBuffer
from engine.db import db
from engine.fusion import fuse
from engine.mocks.world import world
from engine.signals import s3_liveness, s4_context
from engine.stepup import passkeys


@pytest.fixture(autouse=True)
def fresh_world():
    world.reset()
    db.wipe_world()
    yield


# ------------------------------------------------------------------ audio
def test_mulaw_roundtrip_is_close():
    x = np.sin(np.linspace(0, 200, 8000)).astype(np.float32) * 0.5
    y = mulaw_decode(mulaw_encode(x))
    assert len(y) == len(x)
    assert np.max(np.abs(x - y)) < 0.02


def test_mulaw_matches_known_codes():
    # silence encodes to 0xFF, full-scale negative to 0x00 region
    assert mulaw_encode(np.zeros(1, dtype=np.float32)) == b"\xff"
    assert mulaw_decode(b"\xff")[0] == 0.0


def test_phone_line_keeps_length():
    x = np.random.randn(16000).astype(np.float32) * 0.1
    assert abs(len(phone_line(x)) - 16000) <= 2


def test_ring_buffer_wraps():
    r = RingBuffer(1.0, 10)
    r.write(np.arange(7, dtype=np.float32))
    r.write(np.arange(7, 14, dtype=np.float32))
    assert r.total == 14
    assert r.last(10).tolist() == list(range(4, 14))
    assert r.span(10, 13).tolist() == [10, 11, 12]
    r.wipe()
    assert r.total == 0 and r.last(5).size == 0


# ------------------------------------------------------------------ fusion
def test_genuine_voice_is_green_and_clone_is_red():
    assert fuse([0.02, 0.05, 0.03], None, None, []).tier == "GREEN"
    v = fuse([0.95, 0.9, 0.97], None, None, [])
    assert v.tier == "RED" and "SYN_ARTIFACT_HIGH" in v.reasons


def test_context_raises_one_step_never_lowers():
    v = fuse([0.02, 0.03], None, None, ["CLI_MISMATCH"])
    assert v.voice_tier == "GREEN" and v.tier == "AMBER" and "CLI_MISMATCH" in v.reasons
    v = fuse([0.95, 0.95], None, None, ["CLI_MISMATCH"])
    assert v.tier == "RED"


def test_failed_liveness_pushes_amber_to_red():
    amber = fuse([0.45, 0.5, 0.4], None, None, [])
    assert amber.tier == "AMBER"
    red = fuse([0.45, 0.5, 0.4], None, {"reasons": ["RESP_LAG"], "lag_s": 2.4}, [])
    assert red.tier == "RED" and "RESP_LAG" in red.reasons
    assert any("2.4 s" in t for t in red.reason_text)


def test_reasons_capped_at_three():
    v = fuse([0.99] * 5, 0.9, {"reasons": ["RESP_LAG", "CHALLENGE_MISMATCH"], "lag_s": 3}, ["CLI_MISMATCH", "FRI_HIGH"])
    assert len(v.reasons) == 3


# ------------------------------------------------------------------ context
def test_s4_flags():
    rahul = world.customer("rahul")
    assert s4_context.evaluate("rahul", rahul.registered_mobile).flags == []
    assert "CLI_MISMATCH" in s4_context.evaluate("rahul", "+919999999999").flags
    world.sim_swaps[rahul.registered_mobile] = time.time() - 3600
    assert "SIM_SWAP_RECENT" in s4_context.evaluate("rahul", rahul.registered_mobile).flags
    assert "FRI_HIGH" in s4_context.evaluate("rahul", "+918877665544").flags


# ------------------------------------------------------------------ policy
@pytest.mark.parametrize("action,tier,expected", [
    ("block_card", "RED", []),
    ("balance", "AMBER", []),
    ("account_details", "GREEN", ["standard_checks"]),
    ("account_details", "AMBER", ["standard_checks", "liveness"]),
    ("account_details", "RED", ["app_approval"]),
    ("change_mobile", "GREEN", ["standard_checks", "app_approval"]),
    ("add_payee", "AMBER", ["app_approval", "liveness"]),
    ("change_mobile", "RED", ["app_approval", "cooloff_24h", "fraud_desk", "alert_customer"]),
])
def test_policy_matrix(action, tier, expected):
    assert policy.cell(action, tier)["requirements"] == expected


def test_high_risk_cannot_execute_without_app_approval():
    r = policy.create_request("rahul", "contact_centre", "change_mobile", {"new_mobile": "+917777777777"}, "GREEN")
    policy.mark(r["id"], "standard_checks", "met", by="agent")
    with pytest.raises(policy.PolicyError, match="app_approval"):
        policy.execute(r["id"], "agent")
    policy.mark(r["id"], "app_approval", "met", by="rahul")
    policy.execute(r["id"], "agent")
    assert world.customer("rahul").registered_mobile == "+917777777777"


def test_override_refused_on_red_and_never_waives_app_approval():
    r = policy.create_request("rahul", "contact_centre", "change_mobile", {}, "RED")
    with pytest.raises(policy.PolicyError, match="RED"):
        policy.override(r["id"], "liveness", "meera", "customer insists")
    r2 = policy.create_request("rahul", "contact_centre", "add_payee", {}, "AMBER")
    with pytest.raises(policy.PolicyError):
        policy.override(r2["id"], "app_approval", "meera", "trust me")


def test_red_request_needs_cooloff_even_after_approval():
    r = policy.create_request("rahul", "contact_centre", "change_mobile", {}, "RED")
    assert policy.get(r["id"])["policy"]["reqs"]["alert_customer"]["status"] == "met"  # auto-alert
    policy.mark(r["id"], "app_approval", "met", by="rahul")
    policy.mark(r["id"], "fraud_desk", "met", by="analyst")
    with pytest.raises(policy.PolicyError, match="cooloff_24h"):
        policy.execute(r["id"], "agent")


def test_tier_escalation_adds_requirements_and_never_relaxes():
    r = policy.create_request("rahul", "contact_centre", "change_mobile", {}, "GREEN")
    r = policy.escalate(r["id"], "RED")
    assert {"cooloff_24h", "fraud_desk", "standard_checks"} <= set(r["policy"]["reqs"])
    r = policy.escalate(r["id"], "AMBER")  # lower tier: ignored
    assert r["tier"] == "RED"


def test_declining_voice_check_routes_to_app_approval():
    r = policy.create_request("rahul", "contact_centre", "account_details", {}, "AMBER")
    r = policy.decline_voice_check(r["id"], "agent")
    assert r["policy"]["reqs"]["liveness"]["status"] == "replaced"
    assert "app_approval" in r["policy"]["reqs"]


# ------------------------------------------------------------------ liveness
def test_digits_parsing_across_languages():
    assert s3_liveness.digits_in("four seven two nine") == "4729"
    assert s3_liveness.digits_in("चार सात दो नौ") == "4729"
    assert s3_liveness.digits_in("chaar saat do nau") == "4729"
    assert s3_liveness.digits_in("4 7 2 9.") == "4729"


def test_content_match():
    ch = s3_liveness.Challenge("x", "phrase", "say", expect_digits="47", variants=["neela tota", "नीला तोता", "blue parrot"])
    assert s3_liveness.content_match(ch, "नीला तोता सैंतालीस 47") > 0.8
    assert s3_liveness.content_match(ch, "hello I lost my phone") < 0.6


def test_judge_lag():
    ch = s3_liveness.Challenge("x", "digits", "say", expect_digits="1234")
    assert s3_liveness.judge(ch, 0.6, 1.0, 0.05).passed
    res = s3_liveness.judge(ch, 2.4, 1.0, 0.05)
    assert not res.passed and "RESP_LAG" in res.reasons


# ------------------------------------------------------------------ approvals
def test_approval_challenge_is_bound_to_summary():
    a = passkeys._bind({"amount": 50000, "payee": "x"}, b"n" * 16)
    b = passkeys._bind({"amount": 50001, "payee": "x"}, b"n" * 16)
    assert a != b and len(a) == 32


def test_approve_requires_signature_decline_does_not():
    r = policy.create_request("rahul", "contact_centre", "add_payee", {}, "GREEN")
    a = passkeys.request_approval(r["id"], "rahul", "app_approval", {"question": "?"})
    with pytest.raises(passkeys.StepUpError):
        passkeys.decide(a["id"], "approve", None, "localhost", "http://localhost:8000")
    assert passkeys.decide(a["id"], "decline", None, None, None)["status"] == "declined"


# ------------------------------------------------------------------ evidence
def test_clip_encryption_roundtrip_and_audit():
    c = cases.open_case(channel="contact_centre", customer_id="rahul", call_id="call_t", tier="RED", reasons=["SYN_ARTIFACT_HIGH"])
    audio = (np.random.randn(16000 * 3) * 0.1).astype(np.float32)
    cases.attach_clip(c["id"], audio)
    stored = db.get("cases", c["id"])
    blob = open(stored["clip_path"], "rb").read()
    assert b"RIFF" not in blob  # encrypted at rest
    wav = cases.read_clip(c["id"], "analyst_1")
    assert wav[:4] == b"RIFF"
    assert db.query("SELECT 1 FROM audit WHERE event='clip_played' AND actor='analyst_1'")


def test_false_alarm_deletes_clip():
    c = cases.open_case(channel="contact_centre", customer_id="rahul", call_id="call_u", tier="RED")
    cases.attach_clip(c["id"], np.zeros(16000, dtype=np.float32))
    cases.resolve(c["id"], "false_alarm", "analyst")
    assert db.get("cases", c["id"])["clip_path"] is None


# ------------------------------------------------------------------ Entry B guard
def test_guard_fires_after_call_for_new_payee_big_amount():
    world.recent_calls["sunita"] = time.time() - 120
    res = guard.start_payment("sunita", "quickhelp.relief@okaxis", 50000)
    assert res["status"] == "paused"
    assert any("call" in r for r in res["guard"]["reasons"])


def test_guard_quiet_for_usual_payment():
    res = guard.start_payment("sunita", "doodhwala.lko@okicici", 900)
    assert res["status"] == "executed"


def test_family_decline_cancels_and_prefills_1930():
    world.recent_calls["sunita"] = time.time() - 120
    p = guard.start_payment("sunita", "new.person@ybl", 50000)
    a = guard.ask_family(p["payment_id"], "rahul")
    assert "₹50,000" in a["summary"]["question"]
    decided = passkeys.decide(a["id"], "decline", None, None, None)
    guard.on_family_decision(decided)
    assert db.get("requests", p["payment_id"])["status"] == "cancelled"
    assert db.query("SELECT 1 FROM reports WHERE kind='ncrp_1930_prefill'")
    assert world.customer("sunita").balance == 312_900.0


def test_inr_format():
    assert guard._inr(50000) == "₹50,000"
    assert guard._inr(1234567) == "₹12,34,567"
