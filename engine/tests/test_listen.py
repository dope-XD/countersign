"""/ws/listen: the call listener's stronger check, with scripted speech-to-text and a fake judge."""

import asyncio
import time

import numpy as np
import pytest

from engine import callcheck
from engine.listener import live
from engine.listener.fusion import Judge
from engine.mocks.world import world
from engine.signals import s3_liveness
from engine.tests.test_mobile import Phone, client, family  # noqa: F401  (client is a fixture)

SCRIPT = [
    "this is inspector sharma from mumbai police cyber crime",
    "there is an arrest warrant against you for money laundering",
    "stay on the video call and do not tell anyone in your family",
    "transfer your savings to the rbi safe account for verification",
]
FRAME = (np.zeros(1600, dtype="<i2")).tobytes()  # 100 ms; the fake VAD below decides what is speech


class FakeVAD:
    """Every odd frame starts an utterance and every even one ends it."""

    def __init__(self, sample_rate=16000):
        self.n = 0

    def feed(self, x):
        self.n += 1
        return [("onset", 0)] if self.n % 2 else [("offset", 0)]


class FakeJudge:
    calls = 0

    def __init__(self, *a, **k):
        pass

    def judge(self, heard):
        FakeJudge.calls += 1
        return Judge(0.9, "digital_arrest")


@pytest.fixture()
def listen(monkeypatch):
    lines = iter(SCRIPT)
    monkeypatch.setattr(live, "StreamingVAD", FakeVAD)
    monkeypatch.setattr(live, "JUDGE_EVERY_WORDS", 10)
    monkeypatch.setattr(s3_liveness.asr, "transcribe", lambda audio, hint="", language=None: next(lines, ""))
    monkeypatch.setattr("engine.listener.judge.OllamaJudge", FakeJudge)
    FakeJudge.calls = 0


@pytest.fixture()
def fam(client):  # noqa: F811
    mom, son = Phone(client, "Asha Verma"), Phone(client, "Rohan Verma")
    family(mom, son, a_calls_b="Rohan", b_calls_a="Mom")
    return mom, son


def first_verdict(ws):
    while True:
        m = ws.receive_json()
        if m["type"] == "listen_verdict":
            return m


def test_streamed_call_reaches_scam_and_alarms_the_family(fam, listen):
    """The session on its own: audio frames in, verdicts out, and the alarm raised at scam."""
    mom, son = fam
    son.get("/api/m/home")
    sent, alarms = [], []

    async def send(m):
        sent.append(m)
        return True

    async def go():
        sess = live.ListenSession(mom.id, "c1", "en", s3_liveness.asr.transcribe, FakeJudge().judge, send, alarms.append)
        await sess.on_context(["unknown_number"], None)
        for _ in SCRIPT:
            await sess.on_audio(FRAME)
            await sess.on_audio(FRAME)
            for _ in range(20):  # let speech-to-text and the judge finish
                await asyncio.sleep(0.01)
        await sess.close()
        return sess

    sess = asyncio.run(go())
    levels = [m["level"] for m in sent]
    assert "warn" in levels and levels[-1] == "scam"
    assert sent[-1]["scam_type"] == "digital_arrest" and "authority" in sent[-1]["cues"] and sent[-1]["p_scam"] == 0.9
    assert len(alarms) == 1 and FakeJudge.calls >= 1
    assert sess.heard == []  # the transcript goes when the socket closes


def test_server_verdict_raises_the_family_alarm(client, fam, listen):  # noqa: F811
    mom, son = fam
    son.get("/api/m/home")
    with client.websocket_connect("/ws/listen?call_id=c9&lang=en", headers=mom.h()) as ws:
        ws.send_text('{"type": "context", "signals": ["remote_app_opened"]}')
        assert first_verdict(ws)["level"] == "warn"
        for _ in SCRIPT:
            ws.send_bytes(FRAME)
            ws.send_bytes(FRAME)
        for _ in range(200):
            if (mom.id, "c9") in callcheck._alerts:
                break
            time.sleep(0.02)
    assert (mom.id, "c9") in callcheck._alerts
    assert callcheck.scam_for(mom.id)["reason"].startswith("listener:")


def test_caller_check_context_counts(client, fam, listen):  # noqa: F811
    mom, _ = fam
    with client.websocket_connect("/ws/listen?call_id=c2&lang=en", headers=mom.h()) as ws:
        ws.send_text('{"type": "context", "signals": [], "caller_check": "not_them"}')
        m = first_verdict(ws)
        assert m["level"] == "warn" and m["scam_type"] == "impersonation"


def test_listen_needs_a_signed_in_phone_and_consent(client, fam, listen):  # noqa: F811
    mom, _ = fam
    with client.websocket_connect("/ws/listen?call_id=c3") as ws:
        assert ws.receive()["type"] == "websocket.close"
    world.customer(mom.id).stronger_check = False
    with client.websocket_connect("/ws/listen?call_id=c3", headers=mom.h()) as ws:
        assert ws.receive()["code"] == 4403


def test_token_in_the_query_also_works(client, fam, listen):  # noqa: F811
    mom, _ = fam
    with client.websocket_connect(f"/ws/listen?call_id=c4&token={mom.token}") as ws:
        ws.send_text('{"type": "context", "signals": ["remote_app_opened"]}')
        assert first_verdict(ws)["level"] == "warn"
