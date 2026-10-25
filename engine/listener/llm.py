"""The smarter check: an on-phone language model reads a call once it's at warn (port of record for data/listen/Llm.kt).

    prompt(transcript, signals)  # assets/llm_prompt.txt filled in: the last ~1,500 characters and the signal ids
    parse(model_output)          # → LlmVerdict, or None when the output isn't usable

The phone runs Gemma 4 E2B on LiteRT-LM (LlmCheck.kt); ml/eval/llm_confirm.py runs the same weights family on a
laptop (Ollama / llama.cpp) with this exact prompt and parser. The verdict counts as one source (hybrid.py): `scam`
at warn makes scam (if fusion.json llm.can_raise), `ok` and `unsure` never lower the level.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import cache

from engine.callcheck import SCAM_TYPES
from engine.listener.rules import ASSETS

MAX_CHARS = 1500
MAX_REASON = 160
VERDICTS = ("scam", "unsure", "ok")


@dataclass(frozen=True)
class LlmVerdict:
    verdict: str  # scam | unsure | ok
    type: str = "unknown"
    reason_en: str = ""
    reason_hi: str = ""


@cache
def template() -> str:
    return (ASSETS / "llm_prompt.txt").read_text(encoding="utf-8")


def tail(transcript: str, max_chars: int = MAX_CHARS) -> str:
    """The end of the call so far: the last [max_chars] characters, cut at a word boundary."""
    t = " ".join(transcript.split())
    if len(t) <= max_chars:
        return t
    cut = t[-max_chars:]
    i = cut.find(" ")
    return cut[i + 1 :] if 0 <= i < 40 else cut


def prompt(transcript: str, signals: set[str] | list[str] | frozenset[str], tmpl: str | None = None) -> str:
    sig = ", ".join(sorted(signals)) or "nothing"
    return (tmpl or template()).replace("{signals}", sig).replace("{transcript}", tail(transcript))


def _clean(s: object) -> str:
    t = " ".join(str(s).split()) if isinstance(s, str) else ""
    return t[:MAX_REASON]


def parse(output: str) -> LlmVerdict | None:
    """The first JSON object in the model's output (it may wrap it in ``` fences or add words around it)."""
    m = re.search(r"\{.*?\}", output, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(d, dict):
        return None
    v = str(d.get("verdict", "")).strip().lower()
    if v not in VERDICTS:
        return None
    t = str(d.get("type", "unknown")).strip().lower()
    return LlmVerdict(v, t if t in SCAM_TYPES else "unknown", _clean(d.get("reason_en")), _clean(d.get("reason_hi")))


def vectors() -> dict:
    """Shared vectors for HybridTest.kt: prompts built from transcripts and signals, and model outputs parsed."""
    long = " ".join(f"w{i}" for i in range(500)) + " transfer the money to the RBI safe account"
    prompts = [
        {"transcript": t, "signals": sorted(sig), "prompt": prompt(t, sig)}
        for t, sig in [
            ("hello   is this Mrs Sharma", set()),
            ("मैं पुलिस से बोल रहा हूँ, आपका पार्सल पकड़ा गया है", {"unknown_number", "international_number"}),
            (long, {"unknown_number", "remote_app_opened", "digits_read_out"}),
        ]
    ]
    outputs = [
        '{"verdict": "scam", "type": "digital_arrest", "reason_en": "They threaten arrest and ask for money.", "reason_hi": "गिरफ़्तारी की धमकी देकर पैसे मांग रहे हैं।"}',
        '```json\n{"verdict": "ok", "type": "unknown", "reason_en": "A real delivery.", "reason_hi": "असली डिलीवरी।"}\n```',
        'Here is my answer: {"verdict": "UNSURE", "type": "Bank_KYC", "reason_en": "  could   be  a bank  "} thanks',
        '{"verdict": "scam", "type": "not_a_type", "reason_en": "' + "long reason " * 30 + '"}',
        '{"verdict": "probably"}',
        "I can't tell.",
        '{"verdict": "scam", "type": "otp_upi", "reason_en": 5}',
    ]
    parsed = []
    for o in outputs:
        r = parse(o)
        parsed.append({"output": o, "parsed": None if r is None else r.__dict__})
    return {"prompts": prompts, "parse": parsed}


if __name__ == "__main__":
    path = ASSETS.parents[1] / "test" / "resources" / "llm_vectors.json"
    path.write_text(json.dumps(vectors(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {path}")
