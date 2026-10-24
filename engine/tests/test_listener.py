"""The call listener's cue rules and fusion (engine/listener/), on the shared transcripts the app's tests also use."""

import pytest

from engine.listener import fixtures
from engine.listener.fusion import Judge, Verdict, fuse
from engine.listener.rules import CallScorer, normalize, score_text, word_matches

TRANSCRIPTS = fixtures.load()["transcripts"]


@pytest.mark.parametrize("t", TRANSCRIPTS, ids=[t["id"] for t in TRANSCRIPTS])
def test_shared_transcript(t):
    v = fixtures.run(t)
    assert fixtures.problems(t, v) == []
    # the Kotlin port is checked against this exact result
    assert t.get("expect") == {"level": v.level, "type": v.type, "categories": v.cues}, "run python -m engine.listener.fixtures --update"


def test_no_harmless_call_reaches_scam_and_every_scam_reaches_warn():
    for t in TRANSCRIPTS:
        level = fixtures.run(t).level
        if t["label"] == "benign":
            assert level != "scam", t["id"]
        else:
            assert level in ("warn", "scam"), t["id"]


def test_normalize_keeps_devanagari_marks_and_drops_punctuation():
    assert normalize("किसी को मत बताना!") == ["किसी", "को", "मत", "बताना"]
    assert normalize("Don't tell, ANYONE.") == ["dont", "tell", "anyone"]


def test_fuzzy_words_tolerate_recognition_errors():
    assert word_matches("warrant", "warant")
    assert word_matches("teamviewer", "teamvewer")
    assert not word_matches("otp", "top")  # short words must be exact


def test_bank_saying_never_share_otp_is_not_a_cue():
    assert "credentials" not in score_text("the bank will never ask for your OTP or PIN").categories
    assert "credentials" not in score_text("OTP kisi ko mat batana").categories  # Hindi puts the negation after
    assert "credentials" in score_text("OTP bata do nahi to account band").categories  # "nahi to" = otherwise


def test_negation_in_the_next_words_is_waited_for():
    s = CallScorer()
    s.feed("please tell me the OTP")
    assert "credentials" in s.result().categories  # provisional
    s.feed("never to anyone, the bank never asks")
    assert "credentials" not in s.result().categories


def test_one_keyword_never_makes_scam():
    v = fuse(score_text("please share the OTP"), {"unknown_number"})
    assert v.level == "watch"


def test_judge_adds_to_cues_but_cannot_act_alone():
    cues = score_text("this is the police, there is a warrant")
    assert fuse(cues, judge=Judge(0.9, "digital_arrest")).level == "scam"
    assert fuse(score_text("hello how are you"), judge=Judge(0.95)).level == "none"
    assert fuse(cues, judge=Judge(0.9, abstain=True)).level == "warn"


def test_strong_context_plus_cues_makes_scam():
    cues = score_text("your kyc is pending, account will be blocked")
    assert fuse(cues).level == "warn"
    assert fuse(cues, {"remote_app_opened"}).level == "scam"
    assert fuse(score_text("hello"), {"caller_check_failed"}).level == "warn"  # context alone stops at warn


def test_trusted_caller_needs_more_evidence():
    cues = score_text("this is the police, there is a warrant")
    assert fuse(cues).level == "warn"
    assert fuse(cues, {"caller_verified"}).level == "watch"


def test_server_verdict_decides_but_user_alert_stands():
    cues = score_text("this is the police, there is a warrant")
    server = Verdict("watch", "unknown", [], ["server"])
    assert fuse(cues, server=server).level == "watch"
    assert fuse(cues, server=server, user=True).level == "scam"
    assert "server" in fuse(cues, server=Verdict("scam", "digital_arrest", [], ["server"])).sources


def test_levels_never_go_down():
    assert fuse(score_text("hello"), prev="warn").level == "warn"
