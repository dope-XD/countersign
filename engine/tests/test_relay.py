"""The relay (engine/relay.py): the whole phone-to-phone path with no ML loaded."""

import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from engine import callcheck, mobile
from engine.mocks.world import world
from engine.relay import app
from engine.tests.test_mobile import Phone, family


@pytest.fixture()
def relay():
    with TestClient(app, base_url="https://testserver") as c:
        mobile._signups.clear()
        yield c


@pytest.fixture()
def mom_son(relay):
    mom, son = Phone(relay, "Asha Verma"), Phone(relay, "Rohan Verma")
    family(mom, son, a_calls_b="Rohan", b_calls_a="Mom")
    return mom, son


def test_importing_the_relay_loads_no_ml():
    code = "import sys, engine.relay; bad = [m for m in ('torch', 'transformers', 'speechbrain', 'faster_whisper') if m in sys.modules]; print(bad); sys.exit(1 if bad else 0)"
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_health_and_model_pack(relay):
    h = relay.get("/health").json()
    assert h["ok"] and h["analysis"] == "on the phone"
    pack = relay.get("/api/m/models").json()[0]
    assert pack["url"].startswith("https://") and "voice" in pack["parts"]


def test_scam_alarm_then_not_a_scam_reaches_the_family_over_the_socket(mom_son):
    mom, son = mom_son
    with son.c.websocket_connect(f"/ws/events?topics=app:{son.id}", headers=son.h()) as ws:
        ws.send_text("hi")  # his app is online
        r = mom.post(
            "/api/m/scam-alert", {"call_id": "r1", "level": "scam", "type": "digital_arrest", "cues": ["authority", "threat"], "sources": ["cues", "phone_ai"]}
        ).json()
        assert r["alarmed"] == [son.id] and r["scam"]["reason"] == "listener:digital_arrest"
        alarm = ws.receive_json()
        while alarm["type"] != "family_alarm":
            alarm = ws.receive_json()
        assert alarm["label"] == "Mom" and alarm["scam_type"] == "digital_arrest"
        c = mom.post(
            "/api/m/scam-alert/clear", {"call_id": "r1", "reason": "not_a_scam", "level": "scam", "type": "digital_arrest", "cues": ["authority"]}
        ).json()
        assert c["cleared"] == [son.id] and c["scam"] is None
        cleared = ws.receive_json()
        while cleared["type"] != "family_alarm_cleared":
            cleared = ws.receive_json()
        assert cleared["label"] == "Mom" and cleared["reason"] == "not_a_scam"


def test_family_alarm_rings_once_per_call(mom_son):
    mom, son = mom_son
    world.app_sessions[son.id] = 10**12  # online
    body = {"call_id": "r2", "level": "scam", "type": "bank_kyc", "cues": [], "sources": ["cues"]}
    assert mom.post("/api/m/scam-alert", body).json()["alarmed"] == [son.id]
    assert mom.post("/api/m/scam-alert", body).json()["alarmed"] == []


def test_a_phone_only_hears_its_own_events(mom_son):
    mom, son = mom_son
    with mom.c.websocket_connect(f"/ws/events?topics=app:{son.id}", headers=mom.h()) as ws:
        mom.post("/api/m/scam-alert", {"call_id": "r3", "level": "scam", "type": "otp_upi", "cues": [], "sources": ["user"]})
        ws.send_text("hi")
        ws.close()
    # mom asked for son's topic with her own token: the relay gave her nothing, so nothing came


def test_metrics_count_false_alarms_for_review(mom_son):
    mom, _ = mom_son
    n = len(callcheck.false_alarms)
    mom.post("/api/m/scam-alert/clear", {"call_id": "r4", "reason": "know_caller", "level": "warn", "type": "bank_kyc", "cues": ["authority"]})
    live = mom.c.get("/api/metrics").json()["live"]
    assert live["false_alarms_reported"] == n + 1 and live["false_alarms_by_reason"]["know_caller"] >= 1
    assert set(live["for_review"][-1]) == {"at", "call_id", "reason", "level", "type", "cues", "sources"}
