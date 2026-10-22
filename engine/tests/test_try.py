"""/try: a judge's sandbox account and the virtual agent, driven through the real softphone socket."""

import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from engine import auth, policy, tryout
from engine.app import app
from engine.audio.codec import mulaw_encode
from engine.db import db
from engine.mocks.world import world
from engine.session import calls
from ml.eval.soft_authenticator import SoftAuthenticator

SPEECH = mulaw_encode((np.random.default_rng(0).standard_normal(12 * 8000) * 0.1).astype(np.float32))


@pytest.fixture()
def judge(monkeypatch):
    """A judge's phone: /try started, so it holds a sandbox customer's cookie."""
    from engine.audio import vad

    monkeypatch.setattr(vad, "_silero_factory", False)  # energy VAD: the noise counts as speech
    monkeypatch.setattr("engine.audio.vad.StreamingVAD.voiced_fraction", lambda *a: 1.0)
    with TestClient(app, base_url="https://testserver") as c:
        r = c.post("/api/try/start")
        assert r.status_code == 200, r.text
        c.customer = r.json()["customer"]
        yield c


def _score(monkeypatch, p: float):
    from engine.signals.s1_synth import S1Result, detector

    monkeypatch.setattr(detector, "score", lambda ws: [S1Result(p, 1.0) for _ in ws])


def _bind_passkey(c) -> SoftAuthenticator:
    cid = c.customer["id"]
    soft = SoftAuthenticator("testserver", "https://testserver")
    opts = c.post(f"/api/app/{cid}/passkey/options").json()
    assert c.post(f"/api/app/{cid}/passkey/verify", json={"credential": soft.register(opts), "device": "judge phone"}).status_code == 200
    return soft


def _call(c):
    """Dial from /try, speak for 12 s, and return the open socket plus the call."""
    # browsers send the Secure login cookie over wss://; Python's cookie jar doesn't, so pass it by hand
    name = auth.customer_cookie_name(c.customer["id"])
    ws = c.websocket_connect(f"/ws/caller?sandbox={c.customer['id']}&lang=en", headers={"cookie": f"{name}={c.cookies[name]}"}).__enter__()
    first = ws.receive_json()
    assert first["type"] == "call", first
    cs = calls.get(first["id"])
    deadline = time.time() + 5
    while cs.status != "live" and time.time() < deadline:
        time.sleep(0.05)
    for i in range(0, len(SPEECH), 160):
        ws.send_bytes(SPEECH[i : i + 160])
    return ws, cs


def _wait(cond, seconds=15.0):
    deadline = time.time() + seconds
    while not cond() and time.time() < deadline:
        time.sleep(0.05)
    assert cond()


def _request(cs) -> dict:
    _wait(lambda: cs.request_ids)
    return policy.get(cs.request_ids[0])


def _messages_until(ws, kind: str) -> list[dict]:
    out = []
    while True:
        m = ws.receive_json()
        out.append(m)
        if m["type"] == kind:
            return out


def _approval_id(cs) -> str:
    _wait(lambda: policy.get(cs.request_ids[0])["policy"]["reqs"]["app_approval"]["status"] == "sent")
    return policy.get(cs.request_ids[0])["policy"]["reqs"]["app_approval"]["approval_id"]


def test_start_gives_each_phone_its_own_account_that_survives_a_reset(judge):
    cid = judge.customer["id"]
    assert tryout.is_sandbox(cid) and judge.get(f"/api/app/{cid}/home").status_code == 200
    other = TestClient(app, base_url="https://testserver")
    assert other.get(f"/api/app/{cid}/home").status_code == 401  # someone else's sandbox stays private
    judge.post("/api/demo/reset", headers={auth.HEADER: "4321"})
    assert world.customer(cid) is not None


def test_a_sandbox_call_needs_that_sandboxes_phone(judge):
    stranger = TestClient(app, base_url="https://testserver")
    with stranger.websocket_connect(f"/ws/caller?sandbox={judge.customer['id']}") as ws:
        assert ws.receive_json()["type"] == "error"


def test_genuine_judge_gets_the_change_with_one_tap(judge, monkeypatch):
    _score(monkeypatch, 0.02)
    soft = _bind_passkey(judge)
    ws, cs = _call(judge)
    try:
        r = _request(cs)
        assert r["action"] == "change_mobile" and set(r["policy"]["reqs"]) == {"standard_checks", "app_approval"}
        aid = _approval_id(cs)
        opts = judge.post(f"/api/approvals/{aid}/options").json()
        assert (
            judge.post(
                f"/api/approvals/{aid}/decide", json={"decision": "approve", "credential": soft.assert_(opts, judge.customer["id"].encode())}
            ).status_code
            == 200
        )
        msgs = _messages_until(ws, "result")
        assert msgs[-1]["outcome"] == "executed"
        assert world.customer(judge.customer["id"]).registered_mobile == r["details"]["new_mobile"]
        assert any(m["type"] == "verdict" for m in msgs) and any(m["type"] == "agent" for m in msgs)
    finally:
        ws.__exit__(None, None, None)


def test_cloned_voice_is_declined_on_the_judges_phone(judge, monkeypatch):
    _score(monkeypatch, 0.97)
    ws, cs = _call(judge)
    try:
        r = _request(cs)
        assert cs.tier == "RED" and "cooloff_24h" in r["policy"]["reqs"]
        aid = _approval_id(cs)  # sent even without a passkey: this phone can still say no
        judge.post(f"/api/approvals/{aid}/decide", json={"decision": "decline"})
        assert _messages_until(ws, "result")[-1]["outcome"] == "declined"
        assert db.query("SELECT 1 FROM cases WHERE call_id=?", [cs.id])
    finally:
        ws.__exit__(None, None, None)


def test_amber_call_gets_the_spoken_challenge_and_a_silent_clone_fails_it(judge, monkeypatch):
    _score(monkeypatch, 0.5)
    monkeypatch.setattr(tryout, "LIVENESS_WAIT_S", 0.5)
    ws, cs = _call(judge)
    try:
        assert "liveness" in _request(cs)["policy"]["reqs"]
        challenge = ws.receive_json()
        while not challenge.get("challenge"):
            challenge = ws.receive_json()
        ws.send_json({"type": "read_done"})  # the phone finished speaking it; the "caller" never answers
        _wait(lambda: cs.liveness is not None)
        assert cs.liveness["passed"] is False and "NO_REPLY" in cs.liveness["reasons"]
        assert challenge["challenge"]
        assert policy.get(cs.request_ids[0])["status"] != "executed"
    finally:
        ws.__exit__(None, None, None)


def test_samples_and_apk_are_served_from_the_try_folder(judge, monkeypatch, tmp_path):
    import dataclasses

    (tmp_path / "samples").mkdir()
    (tmp_path / "samples" / "rahul_clone_xtts.wav").write_bytes(b"RIFF....WAVE")
    (tmp_path / "samples" / "labels.json").write_text('{"rahul_clone_xtts.wav": "Rahul, cloned with XTTS"}')
    monkeypatch.setattr(tryout, "settings", dataclasses.replace(tryout.settings, try_dir=tmp_path))
    info = judge.get("/api/try/info").json()
    assert info == {"samples": [{"id": "rahul_clone_xtts", "label": "Rahul, cloned with XTTS"}], "apk": False}
    assert judge.get("/api/try/samples/rahul_clone_xtts").status_code == 200
    assert judge.get("/api/try/samples/..%2Fx").status_code == 404
    assert judge.get("/download/cs-bank.apk").status_code == 404
    (tmp_path / "cs-bank.apk").write_bytes(b"PK")
    assert judge.get("/download/cs-bank.apk").status_code == 200
