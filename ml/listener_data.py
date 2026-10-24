"""Public text sets for the scam classifier, as one list of rows with fixed, seeded splits.

    python -m ml.listener_data          # fetch (~7 MB) and print the split table

Every row: {"id", "text", "label" (1 scam, 0 harmless), "source", "lang", "type", "split"}.
Splits: "train", "dev" (model and threshold choice), "test" (never trained or tuned on). Texts are
de-duplicated after normalising case, spaces and digits, and no normalised test text appears in train
or dev. Licences were checked on each dataset card on 24 Oct 2026:

  hinglish_calls  ysangam/Indian_Cyber_Scam_PhoneCall_Hinglish_Dataset   Apache-2.0  10,000 rows, only 743 distinct
  bothbosu        BothBosu/scam-dialogue (its own train/test files)        Apache-2.0  US-style call dialogues
  india_sms       anmolshrivastav/scam_ham_india_14_languages            MIT         SMS, English/Hindi/Hinglish rows;
                  its separate indic_test_suite_clean.csv is the test split (other languages: test_other_lang)
  uci_sms         bolewara/hinglish-scam-text-dataset                    CC BY 4.0   UCI SMS Spam + 35 hand-written
                  Hinglish scams; test only (spam is not always a scam, so its "harmless" side is the useful part)
  team_synth      ml/listener_synth.py                                   ours        template calls, train/dev only: hard
                  harmless calls (real bank, police, delivery OTP, family talking about scams) and Devanagari scams
  team_calls      android/app/src/test/resources/scam_transcripts.json   ours        27 hand-written calls; the cue
                  rules were tuned on them, so they're reported but never counted as proof
  adversarial     data/listener/adversarial.jsonl                        ours        evasion and hard harmless cases
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
import re
import sys
import urllib.request
from collections import Counter
from pathlib import Path

from ml import listener_synth

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "datasets" / "text"
HF = "https://huggingface.co/datasets"
FILES = {
    "bothbosu_train.csv": "BothBosu/scam-dialogue/resolve/main/scam-dialogue_train.csv",
    "bothbosu_test.csv": "BothBosu/scam-dialogue/resolve/main/scam-dialogue_test.csv",
    "hinglish.csv": "ysangam/Indian_Cyber_Scam_PhoneCall_Hinglish_Dataset/resolve/main/India_Cyber_Scam_Hinglish_Dataset.csv",
    "india14.csv": "anmolshrivastav/scam_ham_india_14_languages/resolve/main/scam_ham_india_14_languages.csv",
    "india14_suite.csv": "anmolshrivastav/scam_ham_india_14_languages/resolve/main/indic_test_suite_clean.csv",
    "bolewara.json": "bolewara/hinglish-scam-text-dataset/resolve/main/data.json",
}
SEED = 13
IN_SCOPE = {"English": "en", "Hindi": "hi", "Hinglish": "hinglish"}
ADVERSARIAL = ROOT / "data" / "listener" / "adversarial.jsonl"
TEAM = ROOT / "android" / "app" / "src" / "test" / "resources" / "scam_transcripts.json"


def fetch() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    for name, path in FILES.items():
        if not (RAW / name).exists():
            print(f"fetching {name}")
            urllib.request.urlretrieve(f"{HF}/{path}", RAW / name)


def norm(text: str) -> str:
    return re.sub(r"\d+", "0", re.sub(r"\s+", " ", text.lower())).strip()


def _bucket(text: str, salt: str) -> float:
    """A stable number in [0, 1) per normalised text, so a text and its near-copies land in the same split."""
    return int(hashlib.sha1(f"{salt}:{SEED}:{norm(text)}".encode()).hexdigest()[:8], 16) / 2**32


def _csv(name: str) -> list[dict]:
    with open(RAW / name, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _dedup(rows: list[dict]) -> list[dict]:
    seen, out = set(), []
    for r in rows:
        k = norm(r["text"])
        if k and k not in seen:
            seen.add(k)
            out.append(r)
    return out


def _row(i: str, text: str, label: int, source: str, lang: str, type_: str, split: str) -> dict:
    return {"id": i, "text": text.strip(), "label": int(label), "source": source, "lang": lang, "type": type_, "split": split}


def load(with_ours: bool = True) -> list[dict]:
    fetch()
    rows: list[dict] = []

    # Indian Hinglish call lines: 70/10/20 by text
    hin = _dedup([{"text": r["text"], "label": r["label"], "type": r["scam_category"]} for r in _csv("hinglish.csv")])
    for n, r in enumerate(hin):
        b = _bucket(r["text"], "hinglish")
        split = "train" if b < 0.7 else "dev" if b < 0.8 else "test"
        rows.append(_row(f"hinglish_calls/{n}", r["text"], int(r["label"]), "hinglish_calls", "hinglish", r["type"], split))

    # BothBosu: its own test file is our test; 10% of its train file is dev
    for name, base in (("bothbosu_train.csv", "train"), ("bothbosu_test.csv", "test")):
        for n, r in enumerate(_dedup([{"text": r["dialogue"], "label": r["label"], "type": r["type"]} for r in _csv(name)])):
            split = base if base == "test" else ("dev" if _bucket(r["text"], "bothbosu") < 0.1 else "train")
            rows.append(_row(f"bothbosu/{base}/{n}", r["text"], int(r["label"]), "bothbosu", "en", r["type"], split))

    # India SMS: the main file is train/dev (85/15, in-scope languages only), the suite file is test
    sms = _dedup(
        [{"text": r["text"], "label": r["label"] == "scam", "type": "sms", "lang": r["language"]} for r in _csv("india14.csv") if r["language"] in IN_SCOPE]
    )
    for n, r in enumerate(sms):
        split = "dev" if _bucket(r["text"], "india_sms") < 0.15 else "train"
        rows.append(_row(f"india_sms/{n}", r["text"], int(r["label"]), "india_sms", IN_SCOPE[r["lang"]], "sms", split))
    for n, r in enumerate(_dedup([{"text": r["text"], "label": r["label"] == "scam", "lang": r["language"]} for r in _csv("india14_suite.csv")])):
        lang = IN_SCOPE.get(r["lang"])
        rows.append(
            _row(f"india_sms/suite/{n}", r["text"], int(r["label"]), "india_sms", lang or r["lang"].lower(), "sms", "test" if lang else "test_other_lang")
        )

    # UCI SMS spam + hand-written Hinglish: test only
    bol = json.loads((RAW / "bolewara.json").read_text(encoding="utf-8"))["rows"]
    for n, r in enumerate(_dedup([{"text": r["text"], "label": r["label"]} for r in bol])):
        rows.append(_row(f"uci_sms/{n}", r["text"], int(r["label"]), "uci_sms", "en", "sms", "test"))

    if with_ours:
        rows.extend(listener_synth.rows())
        for t in json.loads(TEAM.read_text(encoding="utf-8"))["transcripts"]:
            rows.append(
                _row(f"team_calls/{t['id']}", " ".join(t["turns"]), int(t["label"] == "scam"), "team_calls", t["lang"], t.get("type") or "none", "test")
            )
        if ADVERSARIAL.exists():
            for line in ADVERSARIAL.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    a = json.loads(line)
                    rows.append(_row(f"adversarial/{a['id']}", a["text"], a["label"], "adversarial", a["lang"], a["attack"], "test"))

    # no normalised test text may appear in train or dev
    held = {norm(r["text"]) for r in rows if r["split"].startswith("test")}
    before = len(rows)
    rows = [r for r in rows if r["split"].startswith("test") or norm(r["text"]) not in held]
    if before != len(rows):
        print(f"dropped {before - len(rows)} train/dev rows that also appear in a test set", file=sys.stderr)
    return rows


def table(rows: list[dict]) -> str:
    c = Counter((r["source"], r["split"], r["label"]) for r in rows)
    srcs = sorted({r["source"] for r in rows})
    lines = ["| source | split | scam | harmless |", "|---|---|---:|---:|"]
    for s in srcs:
        for sp in ("train", "dev", "test", "test_other_lang"):
            if c[(s, sp, 1)] or c[(s, sp, 0)]:
                lines.append(f"| {s} | {sp} | {c[(s, sp, 1)]} | {c[(s, sp, 0)]} |")
    return "\n".join(lines)


def shuffled(rows: list[dict], seed: int = SEED) -> list[dict]:
    rows = list(rows)
    random.Random(seed).shuffle(rows)
    return rows


if __name__ == "__main__":
    print(table(load()))
