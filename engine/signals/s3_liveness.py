"""S3: random liveness challenge.

The agent reads a random challenge. We time the gap from the end of the agent's speech
to the start of the caller's reply, check the words with faster-whisper, and re-score the
reply with S1 (clones degrade on unusual delivery). Only pass/fail and timings are kept;
the transcript is discarded.
"""

from __future__ import annotations

import logging
import os
import random
import re
import threading
import unicodedata
from dataclasses import dataclass, field

import numpy as np

from engine.config import settings

log = logging.getLogger(__name__)

COLOURS = [("neela", "नीला", "blue"), ("hara", "हरा", "green"), ("peela", "पीला", "yellow"), ("laal", "लाल", "red"), ("kaala", "काला", "black")]
THINGS = [("tota", "तोता", "parrot"), ("aam", "आम", "mango"), ("ghoda", "घोड़ा", "horse"), ("kitaab", "किताब", "book"), ("chaand", "चांद", "moon")]

NUM_WORDS = {
    # English
    "zero": "0",
    "oh": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    # Hindi, Roman
    "shunya": "0",
    "ek": "1",
    "do": "2",
    "teen": "3",
    "tin": "3",
    "char": "4",
    "chaar": "4",
    "paanch": "5",
    "panch": "5",
    "chhe": "6",
    "chhah": "6",
    "che": "6",
    "saat": "7",
    "sat": "7",
    "aath": "8",
    "ath": "8",
    "nau": "9",
    # Hindi, Devanagari
    "शून्य": "0",
    "एक": "1",
    "दो": "2",
    "तीन": "3",
    "चार": "4",
    "पांच": "5",
    "पाँच": "5",
    "छह": "6",
    "छः": "6",
    "सात": "7",
    "आठ": "8",
    "नौ": "9",
    # Devanagari digits
    "०": "0",
    "१": "1",
    "२": "2",
    "३": "3",
    "४": "4",
    "५": "5",
    "६": "6",
    "७": "7",
    "८": "8",
    "९": "9",
}


@dataclass
class Challenge:
    id: str
    kind: str  # digits | phrase | whisper
    say: str  # what the agent reads out
    expect_digits: str = ""
    variants: list[str] = field(default_factory=list)
    short: bool = True


def new_challenge(rng: random.Random | None = None) -> Challenge:
    rng = rng or random.SystemRandom()
    kind = rng.choice(["digits", "phrase", "phrase", "whisper"])
    cid = f"{rng.getrandbits(32):08x}"
    digits = "".join(rng.choice("123456789") for _ in range(4))
    spaced = " ".join(digits)
    if kind == "digits":
        return Challenge(cid, kind, f"Please repeat these numbers quickly: {spaced}", expect_digits=digits)
    c = rng.choice(COLOURS)
    t = rng.choice(THINGS)
    d2 = digits[:2]
    if kind == "phrase":
        say = f'Please say: "{c[0]} {t[0]} {d2}"'
    else:
        say = f'Please whisper: "{c[0]} {t[0]} {d2}"'
    return Challenge(
        cid,
        kind,
        say,
        expect_digits=d2,
        variants=[f"{c[0]} {t[0]}", f"{c[1]} {t[1]}", f"{c[2]} {t[2]}"],
    )


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFC", s.lower())
    # drop punctuation and symbols only; Devanagari vowel signs are marks, not \w, and must stay
    s = "".join(" " if unicodedata.category(ch)[0] in "PS" else ch for ch in s)
    return re.sub(r"\s+", " ", s).strip()


def digits_in(text: str) -> str:
    out = []
    for tok in _norm(text).split():
        if tok.isdigit():
            out.append(tok)
        elif tok in NUM_WORDS:
            out.append(NUM_WORDS[tok])
        else:
            # Devanagari digits inside a token
            conv = "".join(NUM_WORDS.get(ch, "") for ch in tok)
            if conv:
                out.append(conv)
    return "".join(out)


def content_match(ch: Challenge, transcript: str) -> float:
    """0..1: how well the reply matches the challenge."""
    from rapidfuzz import fuzz

    t = _norm(transcript)
    if not t:
        return 0.0
    digit_score = 1.0
    if ch.expect_digits:
        got = digits_in(t)
        digit_score = fuzz.ratio(got, ch.expect_digits) / 100 if got else 0.0
    if not ch.variants:
        return digit_score
    words = max(fuzz.partial_ratio(_norm(v), t) for v in ch.variants) / 100
    return 0.5 * digit_score + 0.5 * words


class ASR:
    def __init__(self):
        self.model = None
        self._lock = threading.Lock()

    def load(self) -> None:
        if settings.asr_model == "off":
            log.info("ASR disabled; liveness checks judge timing and S1 only")
            return
        try:
            import torch  # noqa: F401  (puts CUDA / cuDNN DLLs on the search path)

            if os.name == "nt":
                lib = os.path.join(os.path.dirname(torch.__file__), "lib")
                if os.path.isdir(lib):
                    os.add_dll_directory(lib)
            from faster_whisper import WhisperModel

            if settings.device == "cuda" and torch.cuda.is_available():
                try:
                    self.model = WhisperModel(settings.asr_model, device="cuda", compute_type="int8_float16")
                    self._warm()
                    log.info("ASR %s on cuda", settings.asr_model)
                    return
                except Exception as e:
                    log.warning("ASR on GPU failed (%s), using CPU", e)
            self.model = WhisperModel(settings.asr_model, device="cpu", compute_type="int8")
            self._warm()
            log.info("ASR %s on cpu", settings.asr_model)
        except Exception as e:
            log.warning("ASR unavailable: %s", e)

    def _warm(self) -> None:
        list(self.model.transcribe(np.zeros(16000, dtype=np.float32), beam_size=1)[0])

    def transcribe(self, audio16k: np.ndarray, hint: str = "", language: str | None = None) -> str:
        if self.model is None or len(audio16k) < 1600:
            return ""
        with self._lock:
            segs, _info = self.model.transcribe(
                audio16k,
                beam_size=1,
                language=language,
                vad_filter=False,
                condition_on_previous_text=False,
                initial_prompt="Numbers and Hindi or English words. " + hint,
            )
            return " ".join(s.text for s in segs).strip()


asr = ASR()


@dataclass
class LivenessResult:
    challenge_id: str
    lag_s: float | None
    match: float
    s1_reply: float | None
    passed: bool
    reasons: list[str]


def judge(ch: Challenge, lag_s: float | None, match: float, s1_reply: float | None) -> LivenessResult:
    reasons = []
    lag_limit = 1.5 if ch.short else 2.5
    if lag_s is None:
        reasons.append("NO_REPLY")
    elif lag_s > lag_limit:
        reasons.append("RESP_LAG")
    if match < 0.6:
        reasons.append("CHALLENGE_MISMATCH")
    if s1_reply is not None and s1_reply >= settings.red_at:
        reasons.append("SYN_ARTIFACT_HIGH")
    return LivenessResult(ch.id, lag_s, match, s1_reply, passed=not reasons, reasons=reasons)
