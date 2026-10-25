"""The voiceover and the timeline, from script.json.

    python video/tools/vo.py          # check the words, write SCRIPT.md, make the voice, write src/timeline.json

For each scene the voice is video/recorded/<id>.(wav|m4a|mp3) when a team member has recorded it, otherwise a
placeholder from macOS `say` (Rishi, Indian English). Each scene lasts at least its "min" seconds and long enough
for its voice. The music (music/make_music.py) and the scenes are timed from src/timeline.json.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FPS = 60
LEAD = 0.5  # seconds of picture before the voice starts in each scene
TAIL = 0.9  # and after it ends

# Wikipedia, "Signs of AI writing": words and marks that make a script sound machine-written.
BANNED = [
    "delve",
    "crucial",
    "pivotal",
    "tapestry",
    "testament",
    "underscore",
    "showcase",
    "intricate",
    "vibrant",
    "valuable",
    "enduring",
    "landscape",
    "foster",
    "garner",
    "leverage",
    "multifaceted",
    "seamless",
    "robust",
    "cutting-edge",
    "groundbreaking",
    "game-changer",
    "revolutioni",
    "empower",
    "unlock",
    "harness",
    "boasts",
    "serves as",
    "stands as",
    "not just",
    "not only",
    "rather than",
    "in today's",
    "ever-evolving",
    "navigate",
    "realm",
    "elevate",
    "streamline",
    "holistic",
    "paramount",
    "meticulous",
    "comprehensive",
]
MARKS = {"—": "em dash", "–": "en dash", "“": "curly quote", "”": "curly quote", "’": "curly apostrophe"}

# only for the placeholder voice: how `say` should pronounce a few words
SAY = {"GPay": "G Pay", "GPT-4o-mini": "G P T four o mini", "PreScam": "Pree Scam", "OTP": "O T P", "SMS": "S M S"}


def check(scenes: list[dict]) -> None:
    bad = []
    for s in scenes:
        low = s["vo"].lower()
        bad += [f'{s["id"]}: "{w}"' for w in BANNED if w in low]
        bad += [f'{s["id"]}: {name}' for ch, name in MARKS.items() if ch in s["vo"]]
    if bad:
        sys.exit("script.json has AI-sounding words or marks:\n  " + "\n  ".join(bad))


def seconds(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True
    )
    return float(out.stdout.strip())


def voice(s: dict) -> tuple[Path, bool]:
    out = ROOT / "public" / "vo" / f'{s["id"]}.wav'
    rec = next((p for ext in ("wav", "m4a", "mp3") if (p := ROOT / "recorded" / f'{s["id"]}.{ext}').exists()), None)
    if rec:
        # trim the silence at both ends, then level it
        trim = "silenceremove=start_periods=1:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(rec), "-af", f"{trim},loudnorm=I=-16:TP=-1.5", "-ar", "48000", "-ac", "1", str(out)], check=True
        )
        return out, True
    text = s["vo"]
    for w, p in SAY.items():
        text = re.sub(rf"\b{re.escape(w)}\b", p, text)
    aiff = out.with_suffix(".aiff")
    subprocess.run(["say", "-v", "Rishi", "-r", "176", "-o", str(aiff), text], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(aiff), "-af", "loudnorm=I=-16:TP=-1.5", "-ar", "48000", "-ac", "1", str(out)], check=True)
    aiff.unlink()
    return out, False


def script_md(scenes: list[dict]) -> str:
    lines = [
        "# Countersign video: the voiceover",
        "",
        "Read one scene per take, calmly, with a short pause before and after. Save each take as",
        "`video/recorded/<scene>.m4a` (a phone voice memo is fine), then run `python video/tools/vo.py`.",
        "",
    ]
    for s in scenes:
        lines += [f'## {s["id"]}: {s["title"]}', "", s["vo"], ""]
    return "\n".join(lines)


def main() -> None:
    scenes = json.loads((ROOT / "script.json").read_text())["scenes"]
    check(scenes)
    (ROOT / "SCRIPT.md").write_text(script_md(scenes))
    (ROOT / "public" / "vo").mkdir(parents=True, exist_ok=True)
    t, rows = 0.0, []
    for s in scenes:
        path, recorded = voice(s)
        vo = seconds(path)
        dur = max(s["min"], LEAD + vo + TAIL)
        dur = round(dur * FPS) / FPS
        rows.append({"id": s["id"], "start": round(t, 4), "dur": dur, "voStart": LEAD, "voDur": round(vo, 3), "recorded": recorded})
        print(f'{s["id"]}  {t:6.1f}s  {dur:5.1f}s  voice {vo:4.1f}s  {"recorded" if recorded else "placeholder"}')
        t += dur
    (ROOT / "src" / "timeline.json").write_text(json.dumps({"fps": FPS, "total": round(t, 4), "scenes": rows}, indent=1))
    print(f"total {t:.1f}s")


if __name__ == "__main__":
    main()
