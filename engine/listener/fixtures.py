"""The shared test transcripts (android/app/src/test/resources/scam_transcripts.json).

python -m engine.listener.fixtures            # check every transcript, print the misses
python -m engine.listener.fixtures --update   # also write each one's "expect" (the Kotlin port must match it)
"""

from __future__ import annotations

import argparse
import json
import sys

from engine.listener.fusion import LEVELS, Verdict, fuse
from engine.listener.rules import ROOT, CallScorer

PATH = ROOT / "android" / "app" / "src" / "test" / "resources" / "scam_transcripts.json"


def load() -> dict:
    return json.loads(PATH.read_text(encoding="utf-8"))


def run(t: dict) -> Verdict:
    """Feed the turns one by one, as the phone would, carrying the level forward."""
    s, prev = CallScorer(), "none"
    for turn in t["turns"]:
        s.feed(turn)
        prev = fuse(s.result(), set(t["context"]), prev=prev).level
    return fuse(s.result(), set(t["context"]), prev=prev)


def problems(t: dict, v: Verdict) -> list[str]:
    out = []
    if not LEVELS.index(t["min"]) <= LEVELS.index(v.level) <= LEVELS.index(t["max"]):
        out.append(f"level {v.level}, want {t['min']}..{t['max']}")
    if t.get("type") and v.type != t["type"]:
        out.append(f"type {v.type}, want {t['type']}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true")
    a = ap.parse_args()
    d, bad = load(), 0
    for t in d["transcripts"]:
        v = run(t)
        for p in problems(t, v):
            bad += 1
            print(f"{t['id']}: {p}")
        t["expect"] = {"level": v.level, "type": v.type, "categories": v.cues}
    if a.update:
        PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="")
    print(f"{len(d['transcripts'])} transcripts, {bad} problems")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
