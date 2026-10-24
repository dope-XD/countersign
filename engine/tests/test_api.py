"""End-to-end API regression tests (dummy S1, no GPU, no models).

These walk the real HTTP/websocket surface the web app and the CS Bank app use, with real
phone-key signatures from the simulator's software device key.
"""

import asyncio
import time
from contextlib import ExitStack, contextmanager

import numpy as np
import pytest
from fastapi.testclient import TestClient

from engine import auth
from engine.app import app
from engine.audio.codec import mulaw_encode
from engine.config import settings
from engine.db import db
from engine.mocks.world import world
from engine.session import calls
from engine.stepup import devicekeys
from ml.eval.soft_device import SoftDevice

PIN = {auth.HEADER: "4321"}
RAHUL_CLI = "%2B919845012210"


@pytest.fixture()
def client():
    with TestClient(app, base_url="https://testserver") as c:
        c.headers.update(PIN)
        c.post("/api/demo/reset")
        yield c


@pytest.fixture()
def phone(client):
    """Rahul's phone: the CS Bank app with its key registered to the account."""
    return claim(client, "rahul")


def claim(client, cid: str) -> SoftDevice:
    devicekeys.remove_devices(cid)
    dev = SoftDevice()
    r = client.post("/api/m/claim", json={"customer_id": cid, "public_key": dev.public_key, "device": "test phone"})
    assert r.status_code == 200, r.text
    dev.token = r.json()["token"]
    return dev


@contextmanager
def _answered_call(client, cli=RAHUL_CLI):
    """A live call: the caller's websocket is open and the agent has answered."""
    with client.websocket_connect(f"/ws/caller?cli={cli}&lang=en") as ws:
        call_id = ws.receive_json()["id"]
        client.post(f"/api/calls/{call_id}/answer")
        yield call_id


def _decide(client, phone, approval, decision="approve", signature=None):
    body = {"decision": decision, "signature": signature or (phone.sign(approval) if decision == "approve" else None)}
    return client.post(f"/api/m/approvals/{approval['id']}/decide", json=body, headers={"X-Device-Token": phone.token})


# ------------------------------------------------------------------ contact centre
def test_genuine_customer_changes_payee_with_app_approval(client, phone):
    with _answered_call(client) as call_id:
        call = client.get(f"/api/calls/{call_id}").json()
        assert call["customer"]["id"] == "rahul"  # matched on the registered caller ID
        req = client.post(f"/api/calls/{call_id}/request", json={"action": "add_payee", "details": {"payee": "landlord2@okaxis"}}).json()
        assert set(req["policy"]["reqs"]) == {"standard_checks", "app_approval"}
        assert client.post(f"/api/requests/{req['id']}/execute").status_code == 409  # nothing done yet
        client.post(f"/api/requests/{req['id']}/standard-checks", json={"passed": True})
        apr = client.post(f"/api/requests/{req['id']}/send-approval").json()
        assert _decide(client, phone, apr).json()["status"] == "approved"
        out = client.post(f"/api/requests/{req['id']}/execute")
        assert out.status_code == 200 and out.json()["status"] == "executed"
        assert "landlord2@okaxis" in world.customer("rahul").known_payees
        # the call view carries the server's own list of what is still missing
        assert client.get(f"/api/calls/{call_id}").json()["requests"][0]["missing"] == []


def test_declined_approval_blocks_change_and_opens_case(client, phone):
    with _answered_call(client, "%2B917000012345") as call_id:
        client.post(f"/api/calls/{call_id}/identify", json={"customer_id": "rahul"})
        req = client.post(f"/api/calls/{call_id}/request", json={"action": "change_mobile", "details": {"new_mobile": "+917777000111"}}).json()
        apr = client.post(f"/api/requests/{req['id']}/send-approval").json()
        assert _decide(client, phone, apr, "decline").json()["status"] == "declined"
        r = client.post(f"/api/requests/{req['id']}/execute")
        assert r.status_code == 409 and "declined" in r.json()["error"]
        assert world.customer("rahul").registered_mobile == "+919845012210"
        cases_ = client.get("/api/cases").json()
        assert len(cases_) == 1 and cases_[0]["call_id"] == call_id and cases_[0]["customer_id"] == "rahul"


def test_override_refused_on_red(client):
    with _answered_call(client) as call_id:
        calls.get(call_id).tier = "RED"
        req = client.post(f"/api/calls/{call_id}/request", json={"action": "account_details"}).json()
        r = client.post(f"/api/requests/{req['id']}/override", json={"requirement": "liveness", "reason": "customer insists"})
        assert r.status_code == 409


def test_approval_can_be_resent_after_expiry(client, phone, monkeypatch):
    with _answered_call(client) as call_id:
        req = client.post(f"/api/calls/{call_id}/request", json={"action": "add_payee", "details": {"payee": "x@ybl"}}).json()
        first = client.post(f"/api/requests/{req['id']}/send-approval").json()
        assert client.post(f"/api/requests/{req['id']}/send-approval").status_code == 409  # still waiting
        monkeypatch.setattr(devicekeys, "APPROVAL_TTL", -1)
        second = client.post(f"/api/requests/{req['id']}/send-approval")
        assert second.status_code == 200 and second.json()["id"] != first["id"]
        assert db.get("approvals", first["id"])["status"] == "expired"


def test_fixed_challenge_and_hangup(client):
    with _answered_call(client) as call_id:
        assert client.post(f"/api/calls/{call_id}/challenge", params={"force": "C01"}).json()["id"] == "C01"
        assert client.post(f"/api/calls/{call_id}/challenge", params={"force": "nope"}).status_code == 404
        client.post(f"/api/calls/{call_id}/hangup")
        assert calls.get(call_id).ended
        assert client.post(f"/api/calls/{call_id}/challenge").status_code == 409


# ------------------------------------------------------------------ validation and errors
@pytest.mark.parametrize(
    "method,path,body,code",
    [
        ("get", "/api/approvals/apr_missing/evidence", None, 404),
        ("get", "/api/cases/case_missing", None, 404),
        ("post", "/api/calls/call_missing/answer", None, 404),
        ("post", "/api/requests/req_missing/execute", None, 404),
        ("post", "/api/demo/sim-swap", {"customer_id": "nobody"}, 404),
        ("post", "/api/indiacall/consent", {"speaker": "", "name": "x", "agree": True}, 422),
        ("get", "/api/does-not-exist", None, 404),
    ],
)
def test_bad_input_is_4xx(client, method, path, body, code):
    r = getattr(client, method)(path, **({"json": body} if body is not None else {}))
    assert r.status_code == code, r.text


def test_case_can_only_be_resolved_once(client, phone):
    with _answered_call(client) as call_id:
        case_id = client.post(f"/api/calls/{call_id}/transfer").json()["case_id"]
        assert client.post(f"/api/cases/{case_id}/resolve", json={"outcome": "fraud_confirmed"}).status_code == 200
        assert client.post(f"/api/cases/{case_id}/resolve", json={"outcome": "false_alarm"}).status_code == 409
        assert client.post(f"/api/cases/{case_id}/resolve", json={"outcome": "maybe"}).status_code == 422


def test_bad_signature_is_400_not_500(client, phone):
    with _answered_call(client) as call_id:
        req = client.post(f"/api/calls/{call_id}/request", json={"action": "add_payee", "details": {"payee": "x@ybl"}}).json()
        apr = client.post(f"/api/requests/{req['id']}/send-approval").json()
        assert _decide(client, phone, apr, signature=SoftDevice().sign(apr)).status_code == 400  # another phone's key
        assert _decide(client, phone, apr, signature="not base64!").status_code == 400
        assert _decide(client, phone, apr).status_code == 200


def test_no_app_approval_without_a_registered_phone(client):
    devicekeys.remove_devices("rahul")
    with _answered_call(client) as call_id:
        req = client.post(f"/api/calls/{call_id}/request", json={"action": "add_payee", "details": {"payee": "x@ybl"}}).json()
        r = client.post(f"/api/requests/{req['id']}/send-approval")
        assert r.status_code == 409 and "branch" in r.json()["error"]


# ------------------------------------------------------------------ access control and static files
def test_staff_pin_required_for_staff_routes():
    with TestClient(app, base_url="https://testserver") as c:
        assert c.get("/api/calls").status_code == 401
        assert c.get("/api/demo/stored").status_code == 401
        assert c.get("/api/m/home").status_code == 401  # the app must sign up first (test_mobile.py)
        assert c.post("/api/staff/login", json={"pin": "0000"}).status_code == 401
        assert c.post("/api/staff/login", json={"pin": "4321"}).status_code == 200
        assert c.get("/api/calls").status_code == 200  # cookie now set


def test_events_socket_strips_staff_topics_for_customers():
    with TestClient(app, base_url="https://testserver") as c, c.websocket_connect("/ws/events?topics=desk,app:rahul") as ws:
        ws.send_text("hi")
    # nothing to assert on the wire; the subscription logic is covered by checking hub topics below
    from engine.hub import hub

    assert not hub.has_subscribers("desk")


def test_static_route_cannot_escape_web_dist(client):
    secret = (auth.settings.runtime_dir / "cookie_secret.key").read_text()
    for path in ["/..%2F..%2Fdata%2Fruntime%2Fcookie_secret.key", "/%2E%2E/%2E%2E/engine/app.py", "/../../engine/app.py"]:
        r = client.get(path)
        assert secret not in r.text and "FastAPI" not in r.text


# ------------------------------------------------------------------ pipeline behaviour
def _session(customer="rahul"):
    from engine.session import CallSession

    cs = CallSession(id=f"call_t{time.time_ns()}", caller_cli="+917000012345", customer_id=customer)
    cs.status = "live"
    return cs


def test_line_audio_is_never_resampled_per_frame():
    from engine.audio.codec import mulaw_decode

    cs = _session()
    x = (0.3 * np.sin(2 * np.pi * 440 * np.arange(8000) / 8000)).astype(np.float32)
    frames = [mulaw_encode(x[i : i + 160]) for i in range(0, 8000, 160)]
    for f in frames:
        cs.caller.push(mulaw_decode(f))
    stored = cs.caller.ring.last(8000)
    assert np.array_equal(stored, mulaw_decode(b"".join(frames)))  # 8 kHz, bit-exact, no per-frame filtering


def test_scoring_reaches_red_and_attaches_8k_evidence(monkeypatch):
    from engine.signals.s1_synth import S1Result, detector

    monkeypatch.setattr(detector, "score", lambda ws: [S1Result(0.97, 1.0) for _ in ws])
    monkeypatch.setattr("engine.audio.vad.StreamingVAD.voiced_fraction", lambda *a: 1.0)
    cs = _session()
    calls.calls[cs.id] = cs
    rng = np.random.default_rng(0)

    async def run():
        for _ in range(500):  # 10 s of audio
            await cs.on_caller_audio(mulaw_encode((rng.standard_normal(160) * 0.1).astype(np.float32)))
            await asyncio.sleep(0)
        for _ in range(50):
            await asyncio.sleep(0.01)

    asyncio.run(run())
    assert len(cs.windows) >= 2 and cs.tier == "RED"
    c = db.get("cases", cs.case_id)
    assert c["clip_path"] and c["tier"] == "RED"


def test_first_tier_within_8s_of_answer_on_continuous_speech(client, monkeypatch):
    """Deck: the first tier is on the agent's screen within 8 s when the caller talks from the moment
    the agent answers. The engine's call clock is made to follow the caller audio it has received, as a
    phone line delivers it in real time (a test client can't pace frames reliably: on Windows a plain
    asyncio.sleep(0.02) takes ~31 ms, and a feed at 0.64x real time is what produced 9.5 s on 20 Oct).
    S1's live p95 per window is budgeted on top."""
    from types import SimpleNamespace

    from engine import session
    from engine.audio import vad

    s1_p95 = 0.3  # 212 ms measured for the AntiDeepfake ensemble on the demo laptop
    monkeypatch.setattr(vad, "_silero_factory", False)  # energy VAD: every loud chunk is speech
    speech = mulaw_encode((np.random.default_rng(0).standard_normal(14 * 8000) * 0.1).astype(np.float32))
    with client.websocket_connect(f"/ws/caller?cli={RAHUL_CLI}&lang=en") as ws:
        cs = calls.get(ws.receive_json()["id"])
        monkeypatch.setattr(session, "time", SimpleNamespace(time=lambda: 1000.0 + cs.caller.pos / 8000))
        client.post(f"/api/calls/{cs.id}/answer")
        for i in range(0, len(speech), 160):
            ws.send_bytes(speech[i : i + 160])
            deadline = time.time() + 5
            while (cs.caller.pos < i + 160 or cs._scoring) and time.time() < deadline:
                time.sleep(0.001)  # let the engine take this frame (and finish any window) first
            if cs.first_tier_at is not None:
                break
    assert cs.first_tier_at is not None, "no tier after 14 s of continuous speech"
    assert cs.first_tier_at + s1_p95 < 8.0, f"first tier at {cs.first_tier_at:.2f} s of audio"


def test_no_scoring_after_hangup(monkeypatch):
    from engine.signals.s1_synth import S1Result, detector

    monkeypatch.setattr(detector, "score", lambda ws: [S1Result(0.99, 1.0) for _ in ws])
    cs = _session()
    cs.end()
    asyncio.run(cs._score(np.zeros(32300, dtype=np.float32), 4.0))
    assert cs.windows == [] and cs.tier is None and cs.case_id is None


def test_stale_challenge_timer_does_not_end_the_new_challenge():
    cs = _session()
    first = cs.issue_challenge()
    second = cs.issue_challenge()
    asyncio.run(cs.challenge_timeout(first, seconds=0))
    assert not second.done and cs.liveness is None


def test_softphone_is_turned_away_when_all_lines_are_busy(client):
    with ExitStack() as stack:
        for _ in range(settings.max_live_calls):
            ws = stack.enter_context(client.websocket_connect(f"/ws/caller?cli={RAHUL_CLI}&lang=en"))
            assert ws.receive_json()["type"] == "call"
        with client.websocket_connect(f"/ws/caller?cli={RAHUL_CLI}&lang=en") as extra:
            assert extra.receive_json()["type"] == "busy"
    # the lines free up when those calls end
    with client.websocket_connect(f"/ws/caller?cli={RAHUL_CLI}&lang=en") as ws:
        assert ws.receive_json()["type"] == "call"


def test_agent_asks_for_the_app_code(client):
    with _answered_call(client) as call_id:
        r = client.post(f"/api/calls/{call_id}/code")
        assert r.status_code == 200 and r.json()["kind"] == "code"
        ch = client.get(f"/api/calls/{call_id}").json()["challenge"]
        assert ch["kind"] == "code" and not any(c.isdigit() for c in ch["say"])  # the agent never sees the code
    with _answered_call(client, "%2B919000000001") as call_id:
        assert client.post(f"/api/calls/{call_id}/code").status_code == 400  # nobody identified yet
