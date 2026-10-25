"""Rehearse the demo's scripts before going on stage (data/demo/scripts.json, docs/DEMO_SCRIPT.md).

    python -m ml.eval.demo_rehearsal            # text, then audio (TTS → phone line → the phone's speech-to-text)
    python -m ml.eval.demo_rehearsal --text     # text only (seconds)

Each script is fed line by line, as the phone hears a call, through engine/listener/hybrid.py (what the phone runs with
the model pack), on an unknown number, and again with a failed caller check (scene 1: the "friend" isn't on Rahul's
phone). For audio, each line is spoken by an Indian TTS voice (edge-tts), sent through a phone line (clean, G.711,
over the air + G.711) and recognised by the phone's own Silero VAD + Omnilingual 300M (from the model pack).

Gate: a scam script reaches red at least one line before its end (with the caller check, for scripts that use it) and
amber by then without it; a genuine script stays at watch or below. Exit code 1 if any script misses its gate.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import numpy as np

from engine.listener.fusion import LEVELS
from engine.listener.hybrid import HybridCall, analyze_text

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "data" / "demo" / "scripts.json"
TTS = ROOT / "data" / "demo" / "tts"
VOICES = {"en": "en-IN-PrabhatNeural", "hinglish": "en-IN-PrabhatNeural", "hi": "hi-IN-MadhurNeural"}
CHANNELS = ["clean", "g711u", "ota+g711u"]
SYM = {"none": "n", "watch": ".", "warn": "A", "scam": "R"}


def at(level: str, floor: str) -> bool:
    return LEVELS.index(level) >= LEVELS.index(floor)


def speak(text: str, voice: str, path: Path) -> np.ndarray:
    import edge_tts
    import soundfile as sf

    from engine.audio.codec import resample

    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        asyncio.run(edge_tts.Communicate(text, voice).save(str(path)))
    x, sr = sf.read(str(path), dtype="float32", always_2d=False)
    if x.ndim > 1:
        x = x.mean(axis=1)
    return resample(x, sr, 16000).astype(np.float32)


def run(lines_heard: list[list[str]], context: set[str]) -> tuple[list[str], HybridCall]:
    """[lines_heard]: per script line, the segments the phone recognised. The level after each line."""
    h = HybridCall()
    h.set_context(context)
    levels = []
    for segs in lines_heard:
        for s in segs:
            h.feed(s)
        levels.append(h.verdict.level)
    return levels, h


def gate(script: dict, plain: list[str], checked: list[str]) -> str | None:
    n = len(plain)
    if script["label"] == "genuine":
        return None if not at(plain[-1], "warn") else f"genuine call reached {plain[-1]}"
    by = n - 2  # index of the line before the last
    red = checked if script.get("caller_check", True) else plain
    if red[by] != "scam":
        return f"red only at line {red.index('scam') + 1 if 'scam' in red else '-'} of {n}"
    if not at(plain[by], "warn"):
        return f"no amber by line {by + 1} without the caller check"
    return None


def report(name: str, script: dict, heard: list[list[str]]) -> str | None:
    ctx = set(script["context"])
    plain, h = run(heard, ctx)
    checked, _ = run(heard, ctx | {"caller_check_failed"})
    miss = gate(script, plain, checked)
    print(
        f"  {name:10s} plain {''.join(SYM[x] for x in plain):8s} check✗ {''.join(SYM[x] for x in checked):8s} "
        f"{h.verdict.type:16s} {', '.join(h.verdict.cues[:4]):45s} {'OK' if miss is None else 'MISS: ' + miss}"
    )
    return miss


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", action="store_true", help="text only, no audio")
    a = ap.parse_args()
    d = json.loads(SCRIPTS.read_text(encoding="utf-8"))
    misses = []
    kit = None
    if not a.text:
        from ml.eval.asr_bakeoff import decode_parts, through, vad_segments
        from ml.eval.kit import Phone

        kit = Phone()
    for s in d["scripts"]:
        print(f"{s['id']} ({s['label']}, {s['lang']})")
        if (m := report("text", s, [[line] for line in s["lines"]])) is not None:
            misses.append(f"{s['id']} text: {m}")
        if kit is None:
            continue
        audio = [speak(line, VOICES[s["lang"]], TTS / f"{s['id']}_{i}.mp3") for i, line in enumerate(s["lines"])]
        for ch in CHANNELS:
            heard = [decode_parts(kit.asr, vad_segments(through(x, ch, seed=i))) for i, x in enumerate(audio)]
            if (m := report(ch, s, heard)) is not None:
                misses.append(f"{s['id']} {ch}: {m}")
            if ch == "ota+g711u":
                for line, segs in zip(s["lines"], heard, strict=True):
                    print(f"      said:  {line}\n      heard: {' | '.join(segs)}")
    print("messages (Check a message)")
    for m in d["messages"]:
        v = analyze_text(m["text"])
        ok = (v.level == "scam") if m["label"] == "scam" else not at(v.level, "warn")
        print(f"  {m['id']:28s} {v.level:6s} {v.type:16s} {'OK' if ok else 'MISS'}")
        if not ok:
            misses.append(f"{m['id']}: {v.level}")
    print("\n" + ("All scripts pass." if not misses else "Misses:\n  " + "\n  ".join(misses)))
    return 1 if misses else 0


if __name__ == "__main__":
    sys.exit(main())
