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


def test_classifier_adds_to_cues_but_never_makes_scam_alone():
    cues = score_text("this is the police, there is a warrant")
    assert fuse(cues, judge=Judge(0.99, "digital_arrest")).level == "scam"
    assert fuse(score_text("hello how are you"), judge=Judge(0.99)).level in ("none", "watch", "warn")
    assert fuse(cues, judge=Judge(0.9, abstain=True)).level == "warn"


def test_classifier_sure_its_harmless_vetoes_a_cue_only_warn():
    cues = score_text("this is the police, there is a warrant")
    assert fuse(cues, judge=Judge(0.01)).level == "watch"
    assert fuse(cues, {"remote_app_opened"}, judge=Judge(0.01)).level == "warn"  # strong context still warns


def test_talk_about_scams_never_reaches_scam_through_the_classifier():
    cues = score_text("did you see the news, fake police called aunty and asked for money for a warrant, never pay them")
    assert cues.discussion
    assert fuse(cues, judge=Judge(0.999)).level != "scam"


def test_strong_context_plus_cues_makes_scam():
    cues = score_text("your kyc is pending, account will be blocked")
    assert fuse(cues).level == "warn"
    assert fuse(cues, {"remote_app_opened"}).level == "scam"
    assert fuse(score_text("hello"), {"caller_check_failed"}).level == "warn"  # context alone stops at warn


def test_trusted_caller_needs_more_evidence():
    cues = score_text("this is the police, there is a warrant")
    assert fuse(cues).level == "warn"
    assert fuse(cues, {"caller_verified"}).level == "watch"


def test_an_ai_voice_is_one_piece_of_evidence_never_scam():
    plain = score_text("hello madam how are you")
    assert fuse(plain, context={"synthetic_voice"}).level == "watch"  # alone: a quiet note, no card
    police = score_text("this is the police")
    v = fuse(police, context={"synthetic_voice"})
    assert v.level == "warn" and "voice" in v.sources  # with one scam cue: amber
    assert fuse(plain, context={"synthetic_voice"}, judge=Judge(0.99)).level != "scam"


def test_levels_never_go_down():
    assert fuse(score_text("hello"), prev="warn").level == "warn"


def test_the_servers_stronger_check_can_raise_the_level_but_never_lower_it():
    calm = score_text("hello madam how are you today")
    up = fuse(calm, server=Verdict("scam", "digital_arrest", ["authority", "threat"], ["server"]))
    assert up.level == "scam" and up.type == "digital_arrest" and "server" in up.sources
    police = score_text("this is the police, there is a warrant in your name, transfer the money to the safe account now")
    assert fuse(police, server=Verdict("none", "unknown", [], ["server"])).level == fuse(police).level


def test_a_boss_ordering_a_secret_payment_to_a_new_account_is_its_own_type():
    v = score_text("this is your MD speaking, I am in a board meeting, keep this between us and process the payment to the new vendor account, it is urgent")
    assert v.type == "boss_payment"
