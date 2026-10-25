"""The two judges together, the smarter check's words, and the signals derived from what was said (CONTRACT.md "Call listener")."""

import json

from engine.listener import hybrid, llm
from engine.listener.fusion import Verdict, fuse
from engine.listener.hybrid import combine, derived
from engine.listener.llm import LlmVerdict, parse, prompt
from engine.listener.rules import ASSETS, digit_runs, digits_read_out, normalize, score_text

NONE = Verdict("none", "unknown", [], [])
SCAM = LlmVerdict("scam", "digital_arrest", "They threaten arrest and ask for money.", "वे पैसे मांग रहे हैं।")


def v(level: str, sources=("cues",), alone=False, cues=("authority",)) -> Verdict:
    return Verdict(level, "unknown", list(cues), list(sources), alone)


# ---------------------------------------------------------------- a context signal counts once
def test_an_international_call_and_one_cue_word_is_not_a_scam():
    # before: the international number counted as a cue category too, so one word reached warn and then scam
    r = fuse(score_text("please share the OTP"), {"unknown_number", "international_number"})
    assert r.level == "warn"
    assert fuse(score_text("please share the OTP, the police have a warrant"), {"unknown_number", "international_number"}).level == "scam"


def test_a_strong_signal_pairs_with_what_was_said_instead_of_counting_as_a_cue():
    cues = score_text("this is the police, there is a warrant, transfer the money")
    assert fuse(cues, set()).level == "warn"
    r = fuse(cues, {"international_number"})
    assert r.level == "scam" and not r.alone and "context" in r.sources


# ---------------------------------------------------------------- what a victim says, and digits read out
def test_what_a_victim_says_is_a_cue():
    assert "victim_says" in score_text("haan ji, otp bata doon? kaunsa app download karun").categories
    assert "victim_says" in score_text("where should I send the money sir, I have not done anything wrong").categories
    assert "victim_says" in score_text("मैंने कुछ नहीं किया, पैसे कहां भेजने हैं").categories
    assert "victim_says" not in score_text("haan beta, khana kha liya, kal milte hain").categories


def test_digits_read_out():
    assert digit_runs(normalize("my otp is 4 5 2 1 okay")) == [4]
    assert digit_runs(normalize("char paanch do ek")) == [4]
    assert digit_runs(normalize("चार पांच दो एक सात आठ")) == [6]
    assert digits_read_out(normalize("it is 452 189"))
    assert not digits_read_out(normalize("call me on 9876543210"))  # a phone number is ten digits
    assert not digits_read_out(normalize("two people, one car"))


def test_derived_signals_need_an_unknown_caller():
    assert "digits_read_out" in derived({"unknown_number"}, normalize("4 5 2 1"), set())
    assert "digits_read_out" not in derived({"known_contact"}, normalize("4 5 2 1"), set())
    assert "bank_claim_not_1600" in derived({"unknown_number"}, [], {"verification_pretext"})
    assert "bank_claim_not_1600" not in derived({"unknown_number", "series_1600"}, [], {"verification_pretext"})
    assert "bank_claim_not_1600" not in derived({"unknown_number"}, [], {"money_ask"})


def test_a_victim_reading_an_otp_on_an_unknown_call_reaches_warn_not_scam():
    text = "haan ji otp bata doon? 4 5 2 1"
    cues = score_text(text)
    ctx = derived({"unknown_number"}, normalize(text), set(cues.categories))
    assert fuse(cues, ctx).level == "warn"  # two pieces of evidence, but the digits are the phone's signal, counted once


# ---------------------------------------------------------------- combine
def test_watch_and_warn_are_the_higher_of_the_two_judges():
    assert combine(v("warn"), v("watch"), "watch")[0].level == "warn"
    assert combine(v("watch"), v("warn"), "warn")[0].level == "warn"


def test_the_conversation_model_alone_never_makes_scam():
    r, _ = combine(NONE, v("scam", ("phone_ai",)), "scam")
    assert r.level == "warn"
    assert combine(v("warn"), v("scam", ("phone_ai",)), "scam")[0].level == "scam"  # the cue rules agree
    assert combine(NONE, v("scam", ("phone_ai",)), "scam", llm=SCAM)[0].level == "scam"  # the smarter check agrees


def test_the_cue_rules_alone_need_a_second_source_with_the_model_pack():
    alone = v("scam", alone=True)
    assert combine(alone, NONE, "none")[0].level == "warn"  # strong cue words reach amber even with the model quiet
    assert combine(alone, v("watch", ("phone_ai",)), "watch")[0].level == "scam"  # the model hearing something is the second source
    assert combine(alone, None)[0].level == "scam"  # basic mode: as before


def test_a_judge_that_already_paired_two_sources_stands():
    assert combine(v("scam", ("cues", "context")), NONE, "none")[0].level == "scam"
    assert combine(NONE, v("scam", ("phone_ai", "context")), "warn")[0].level == "scam"


def test_the_smarter_check_raises_warn_never_lowers_and_its_reason_shows():
    r, shown = combine(v("warn"), NONE, "watch", llm=SCAM)
    assert r.level == "scam" and "llm" in r.sources and shown == SCAM
    r, shown = combine(v("watch"), NONE, "watch", llm=SCAM)
    assert r.level == "watch" and shown is None  # it only runs at warn; a scam word at watch isn't enough
    for quiet in (LlmVerdict("ok"), LlmVerdict("unsure")):
        r, shown = combine(v("warn"), NONE, "watch", llm=quiet, prev="warn")
        assert r.level == "warn" and shown is None
    r, shown = combine(v("warn"), NONE, "watch", llm=SCAM, llm_can_raise=False)
    assert r.level == "warn" and shown == SCAM  # failed its gates: the reason only


def test_user_and_server_and_levels_never_go_down():
    assert combine(NONE, NONE, "none", user=True)[0].level == "scam"
    assert combine(NONE, NONE, "none", server=v("scam", ("server",)))[0].level == "scam"
    assert combine(NONE, NONE, "none", prev="warn")[0].level == "warn"


def test_hybrid_vectors_are_current():
    """HybridTest.kt replays hybrid_vectors.json; regenerate with python -m engine.listener.hybrid."""
    path = ASSETS.parents[1] / "test" / "resources" / "hybrid_vectors.json"
    before = path.read_text(encoding="utf-8")
    hybrid.write_vectors()
    assert path.read_text(encoding="utf-8") == before


# ---------------------------------------------------------------- the smarter check's words
def test_prompt_has_the_signals_and_the_end_of_the_call():
    text = "word " * 600 + "transfer the money to the safe account"
    p = prompt(text, {"unknown_number", "remote_app_opened"})
    assert "remote_app_opened, unknown_number" in p
    assert p.count("word") < 400 and "safe account" in p
    assert "{transcript}" not in p and "{signals}" not in p
    assert "What the phone saw: nothing" in prompt("hello", set())


def test_parse_takes_the_first_json_and_checks_it():
    assert parse('```json\n{"verdict": "scam", "type": "bank_kyc", "reason_en": "Asks for OTP.", "reason_hi": "ओटीपी मांग रहा है।"}\n```') == LlmVerdict(
        "scam", "bank_kyc", "Asks for OTP.", "ओटीपी मांग रहा है।"
    )
    assert parse('Sure! {"verdict": "OK", "type": "nonsense"}') == LlmVerdict("ok", "unknown", "", "")
    assert parse('{"verdict": "maybe"}') is None
    assert parse("no json here") is None
    assert parse('{"verdict": "scam", "reason_en": "' + "x" * 500 + '"}').reason_en == "x" * llm.MAX_REASON


def test_llm_vectors_are_current():
    """HybridTest.kt checks the phone's prompt and parser against llm_vectors.json (python -m engine.listener.llm)."""
    path = ASSETS.parents[1] / "test" / "resources" / "llm_vectors.json"
    assert json.loads(path.read_text(encoding="utf-8")) == llm.vectors()


def test_cue_words_alone_need_the_conversation_model_to_hear_something_for_amber():
    assert combine(v("warn"), NONE, "none")[0].level == "watch"
    assert combine(v("warn", ("cues", "context")), NONE, "none")[0].level == "warn"  # a phone signal still reaches amber
    assert combine(v("warn"), None)[0].level == "warn"  # basic mode: as before


# ---------------------------------------------------------------- intent, not words
GENUINE_ALERT = [
    "Namaste, main HDFC Bank credit card team se Priya bol rahi hoon. Aap Sunita ji bol rahi hain?",
    "Ma'am aapke card par abhi Amazon par chaar hazaar ka ek payment try hua tha, humne usse rok diya hai.",
    "Agar aapne nahi kiya tha toh koi baat nahi, card humne block kar diya hai, naya card paanch din mein ghar aa jayega.",
    "Aur ma'am, bank kabhi bhi call pe OTP ya PIN nahi maangta, toh kisi ko bhi mat batana.",
]
SCAM_TWIN = [
    "Namaste, main HDFC Bank credit card team se Rohit bol raha hoon. Aap Sunita ji bol rahi hain?",
    "Ma'am aapke card par abhi Amazon par pachaas hazaar ka payment hua hai, aapka card hack ho gaya hai.",
    "Ghabraiye mat, main abhi block kar deta hoon. Aapke phone pe ek OTP aayega, woh mujhe bata dijiye.",
    "Aur ma'am abhi kisi ko phone mat kariye, warna account freeze ho jayega. Jaldi bataiye OTP.",
]


def test_a_warning_is_not_an_ask():
    cues = score_text(" ".join(GENUINE_ALERT))
    assert "protective" in cues.categories
    assert fuse(cues, {"unknown_number"}).level in ("none", "watch")  # "OTP" and "mat batana" were the bank warning her


def test_the_same_words_as_an_ask_with_pressure_are_the_playbook():
    from engine.listener.hybrid import playbook

    cues = score_text(" ".join(SCAM_TWIN))
    assert {"direct_ask", "credentials", "secrecy", "threat"} <= set(cues.categories)
    assert playbook(cues.categories)
    assert combine(fuse(cues, {"unknown_number"}), NONE, "none")[0].level == "scam"  # even with the model quiet


def test_amounts_and_now_are_not_asks():
    cats = score_text("aapke card se abhi chaar hazaar ka transaction hua").categories
    assert "money_ask" not in cats and "urgency" not in cats
    assert "discussion" not in score_text("main SBI fraud monitoring team se bol raha hoon").categories


def test_helplines_are_not_digits_read_out():
    assert not digits_read_out(normalize("kuch galat lage toh 1930 pe complaint karna"))
    assert digits_read_out(normalize("otp hai 4 5 2 1"))
