"""The conversation check (engine/listener/conversation.py): tokenizer parity with Hugging Face, the accumulator's
rules, and the shared vectors that ConversationTest.kt also checks."""

from __future__ import annotations

import json

import numpy as np
import pytest

from engine.listener.conversation import Accumulator, Call, Tokenizer, config, text_segments, window
from engine.listener.rules import ASSETS

VECTORS = ASSETS.parents[1] / "test" / "resources" / "conv_vectors.json"


@pytest.fixture(scope="module")
def vectors() -> dict:
    return json.loads(VECTORS.read_text(encoding="utf-8"))


def test_tokenizer_matches_hugging_face(vectors):
    tok = Tokenizer()
    bad = [c["text"][:60] for c in vectors["tokenizer"] if tok.encode(c["text"]) != c["ids"]]
    assert not bad, bad[:5]


def test_windows_and_segments(vectors):
    for c in vectors["windows"]:
        assert window(c["segments"]) == c["window"]
    for c in vectors["text_segments"]:
        assert text_segments(c["text"]) == c["segments"]


def test_accumulator_vectors(vectors):
    for c in vectors["accumulator"]:
        a = Accumulator()
        assert [a.feed(p, set(c["context"])) for p in c["ps"]] == c["levels"]


def test_whole_calls(vectors):
    for c in vectors["calls"]:
        call = Call(p_of=lambda w, p=c["p"]: p[w], embed=lambda t, e=c["emb"]: np.array(e[t], dtype=np.float32))
        call.set_context(set(c["context"]))
        st = call.state()
        for s in c["segments"]:
            st = call.feed(s)
        assert (st.level, st.type, st.reasons, st.sources) == (c["level"], c["type"], c["cues"], c["sources"]), c["id"]


def test_one_odd_segment_is_not_an_alarm():
    cfg = config()
    a = Accumulator()
    a.feed(0.0)
    assert a.feed(min(1.0, cfg["t_warn"] * 1.5)) in ("none", "watch")  # smoothed over two segments
    b = Accumulator()
    assert b.feed(0.999) != "scam"  # scam needs two segments in a row
    assert b.feed(0.999) == "scam"


def test_levels_never_go_down_and_context_counts():
    a = Accumulator()
    a.feed(0.999)
    a.feed(0.999)
    assert a.feed(0.0) == "scam"
    b = Accumulator()
    assert b.feed(0.0, {"caller_check_failed"}) == "warn"  # what the phone saw counts alone
    c = Accumulator()
    assert c.feed(0.0, {"synthetic_voice"}) == "none"  # the voice check alone never warns


def test_trusted_caller_needs_more():
    cfg = config()
    p = (cfg["t_warn"] + cfg["trusted"]["t_warn"]) / 2
    if not cfg["t_warn"] < p < cfg["trusted"]["t_warn"]:
        pytest.skip("thresholds too close")
    a, b = Accumulator(), Accumulator()
    a.feed(p), b.feed(p, {"known_contact"})
    assert a.feed(p) in ("warn", "scam")
    assert b.feed(p, {"known_contact"}) in ("none", "watch")
