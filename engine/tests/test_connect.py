"""Amazon Connect calls through the engine: a signed start notification, then the contact's
KVS media (a synthetic GetMedia stream) into the same scoring path as the softphone."""

import dataclasses
import io
import json
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from engine.app import app
from engine.ingest import connect
from engine.session import calls
from integrations.connect import mkv
from integrations.connect.lambda_start import DEFAULT_PATH, SIGNATURE_HEADER, sign
from integrations.connect.tests import mkvbuild as b

SECRET = "test-secret"
FRAG_S = 1.0
N = int(8000 * FRAG_S)


def noise(seed: int) -> bytes:
    x = np.random.default_rng(seed).standard_normal(N) * 3000
    return x.astype("<i2").tobytes()


def stream(contacts: list[str], spoken_at: float = 1000.0, codec: str = "A_PCM/INT/LIT") -> bytes:
    """One fragment per entry: the caller talks (noise), the agent track is silent."""
    out = b""
    for i, contact in enumerate(contacts):
        caller = noise(i)
        if codec.endswith("BIG"):
            caller = np.frombuffer(caller, "<i2").astype(">i2").tobytes()
        blocks = [(1, 0, caller), (2, 0, b"\x00\x00" * N)]
        tags = {
            "AWS_KINESISVIDEO_FRAGMENT_NUMBER": f"9{i:04d}",
            "AWS_KINESISVIDEO_PRODUCER_TIMESTAMP": f"{spoken_at + i * FRAG_S:.3f}",
            "ContactId": contact,
        }
        out += b.fragment(int(i * FRAG_S * 1000), blocks, tags, codec=codec)
    return out


class SlowStream(io.BytesIO):
    """Arrives in small pieces, like a live GetMedia body."""

    def read(self, n=-1):
        time.sleep(0.02)
        return super().read(min(n, 8192) if n and n > 0 else 8192)


def released(data: bytes, contact: str) -> list[connect.Released]:
    media = connect.ContactMedia(contact)
    out = [r for e in mkv.MkvReader(io.BytesIO(data)) if (r := media.feed(e))]
    if (last := media.finish()) is not None:
        out.append(last)
    return out


def test_only_this_contacts_fragments_are_released():
    rel = released(stream(["c-1", "c-1", "c-2"]), "c-1")
    assert len(rel) == 2  # the pooled stream's next caller never reaches this call
    assert rel[0].spoken_at == 1000.0 and rel[1].spoken_at == 1001.0
    assert set(rel[0].audio) == {connect.CUSTOMER, connect.AGENT}
    assert np.allclose(rel[0].audio[connect.CUSTOMER], connect.pcm16(noise(0)))


def test_big_endian_pcm_is_read_the_same():
    little = released(stream(["c-1"]), "c-1")[0].audio[connect.CUSTOMER]
    big = released(stream(["c-1"], codec="A_PCM/INT/BIG"), "c-1")[0].audio[connect.CUSTOMER]
    assert np.array_equal(little, big)


@pytest.fixture()
def wired(monkeypatch):
    from engine.audio import vad
    from engine.signals.s1_synth import S1Result, detector

    monkeypatch.setattr(connect, "settings", dataclasses.replace(connect.settings, connect_secret=SECRET))
    monkeypatch.setattr(vad, "_silero_factory", False)  # energy VAD: the noise counts as speech
    monkeypatch.setattr(detector, "score", lambda ws: [S1Result(0.97, 1.0) for _ in ws])
    with TestClient(app, base_url="https://testserver") as c:
        yield c


def _start(client, contact: str, attributes: dict | None = None, secret: str = SECRET):
    body = json.dumps(
        {
            "contactId": contact,
            "streamArn": "arn:aws:kinesisvideo:ap-southeast-1:1:stream/countersign-x/1",
            "startFragment": "90000",
            "attributes": attributes or {},
            "sentAt": int(time.time() * 1000),
        }
    ).encode()
    return client.post(DEFAULT_PATH, content=body, headers={SIGNATURE_HEADER: sign(body, secret), "Content-Type": "application/json"})


def test_connect_call_is_scored_like_a_softphone_call(wired, monkeypatch):
    data = stream(["c-9"] * 8 + ["c-10"], spoken_at=time.time() - 9)
    monkeypatch.setattr(connect, "open_media", lambda payload: SlowStream(data))
    r = _start(wired, "c-9", {"cli": "+919845012210", "lang": "hi-IN"})
    assert r.status_code == 202, r.text
    cs = calls.get(r.json()["call_id"])
    assert _start(wired, "c-9").json()["call_id"] == cs.id  # a retried notification doesn't open a second call

    deadline = time.time() + 20
    while not cs.ended and time.time() < deadline:
        time.sleep(0.05)
    assert cs.ended, "the call should end when the stream moves to the next contact"
    assert cs.source == "connect" and cs.language == "hi"
    assert cs.customer_id == "rahul"  # matched on the cli attribute
    assert cs.caller.pos == 8 * N  # c-10's fragment never reached it
    assert len(cs.windows) >= 2 and cs.tier == "RED"
    assert cs.media_delay_s is not None and cs.media_delay_s < 30
    assert "c-9" not in connect.active


def test_connect_start_needs_the_shared_secret(wired):
    assert _start(wired, "c-1", secret="wrong").status_code == 401


def test_connect_ingest_is_off_without_a_secret():
    with TestClient(app, base_url="https://testserver") as c:
        assert _start(c, "c-1").status_code == 404
