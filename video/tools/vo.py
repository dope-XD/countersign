"""The voiceover and the timeline, from script.json.

    python video/tools/vo.py          # check the words, write the scripts, make the voice, write src/timeline.json

Writes SCRIPT.md (to read aloud) and elevenlabs/ (ElevenLabs v3/v4 scenes, a one-paste Multilingual v2 script, a
pronunciation dictionary). The voice for each scene is, in order of preference:
  1. video/recorded/<id>.(mp3|wav|m4a|ogg|flac), one take per scene;
  2. video/recorded/full.(...), one take of the whole script, cut into scenes at its 9 longest pauses;
  3. a placeholder from macOS `say` (Rishi, Indian English).
Each scene lasts at least its "min" seconds and long enough for its voice. Inside a scene, every sentence start is
pinned to the pause before it in the audio (`anchors`), so captions land on the words. The music
(music/make_music.py) and the scenes are timed from src/timeline.json.
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

EXTS = ("mp3", "wav", "m4a", "ogg", "flac")

# for ElevenLabs: numbers as they should be said (normalisation is good, but these are the ones that matter)
SPOKEN = {
    "88 percent": "eighty-eight percent",
    "28 of the 30": "twenty-eight of the thirty",
    "scored 83": "scored eighty-three",
    "at most 70": "at most seventy",
    "A 2026 study": "A twenty twenty-six study",
}
# and the pronunciation dictionary (alias rules work on every model)
ALIASES = {"CBI": "C B I", "OTP": "O T P", "SMS": "S M S", "GPay": "G Pay", "Countersign": "Counter-sign"}

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


def voice(s: dict, split: dict[str, Path]) -> tuple[Path, bool]:
    out = ROOT / "public" / "vo" / f'{s["id"]}.wav'
    rec = next((p for ext in EXTS if (p := ROOT / "recorded" / f'{s["id"]}.{ext}').exists()), None) or split.get(s["id"])
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


def silences(path: Path, db: int = -38, d: float = 0.15) -> list[tuple[float, float]]:
    """(start, end) of every pause in a file."""
    log = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(path), "-af", f"silencedetect=n={db}dB:d={d}", "-f", "null", "-"], capture_output=True, text=True
    ).stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", log)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", log)]
    return list(zip(starts, ends, strict=False))  # a pause running to the end has no end


def split_full(scenes: list[dict]) -> dict[str, Path]:
    """One take of the whole script -> one file per scene. Each scene should end about where its share of the
    script's characters says; the cut goes in the longest pause near there (preferring the scene breaks the
    script asks for, but working with short gaps too)."""
    full = next((p for ext in EXTS if (p := ROOT / "recorded" / f"full.{ext}").exists()), None)
    if not full:
        return {}
    total = seconds(full)
    gaps = silences(full, -40, 0.2)
    sizes = [len(s["vo"]) for s in scenes]
    cuts, done = [0.0], 0
    for k in range(len(scenes) - 1):
        done += sizes[k]
        guess = done / sum(sizes) * total
        win = max(2.5, 0.15 * total * sizes[k] / sum(sizes) + 1.5)
        near = [(a, b) for a, b in gaps if abs((a + b) / 2 - guess) < win and (a + b) / 2 > cuts[-1] + 1]
        if not near:
            sys.exit(f"{full.name}: no pause near {guess:.1f}s (end of {scenes[k]['id']}). Leave a short pause between scenes.")
        # the longest pause wins; closeness to the guess breaks ties
        a, b = max(near, key=lambda g: (g[1] - g[0]) - 0.05 * abs((g[0] + g[1]) / 2 - guess))
        cuts.append((a + b) / 2)
    cuts.append(total)
    out = ROOT / "recorded" / "_split"
    out.mkdir(exist_ok=True)
    parts = {}
    for i, sc in enumerate(scenes):
        p = out / f'{sc["id"]}.wav'
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(full), "-ss", f"{cuts[i]:.3f}", "-to", f"{cuts[i + 1]:.3f}", str(p)], check=True)
        parts[sc["id"]] = p
    print(f"{full.name}: cut into {len(parts)} scenes at " + ", ".join(f"{c:.1f}s" for c in cuts[1:-1]))
    return parts


def anchors(path: Path, text: str, dur: float) -> list[list[float]]:
    """[char index in text, seconds] for the start, every sentence that begins after a pause, and the end."""
    starts = [m.end() for m in re.finditer(r"[.?!:]\s+", text)]
    pauses = [b for a, b in silences(path) if a > 0.05 and b < dur - 0.05]  # when speech resumes
    out, last = [[0, 0.0]], 0.0
    for c in starts:
        guess = c / len(text) * dur
        near = [p for p in pauses if p > last + 0.2 and abs(p - guess) < max(1.2, 0.12 * dur)]
        if near:
            last = min(near, key=lambda p: abs(p - guess))
            out.append([c, round(last, 3)])
    out.append([len(text), round(dur, 3)])
    return out


def spoken(s: dict, v2: bool) -> str:
    """The scene's line as ElevenLabs should get it: numbers said out, a beat before marked phrases, and (v3/v4) the
    delivery in audio tags."""
    text = s["vo"]
    for a, b in SPOKEN.items():
        text = text.replace(a, b)
    for phrase in s.get("pause", []):
        text = text.replace(phrase, ('<break time="0.6s" /> ' if v2 else "... ") + phrase, 1)
    if not v2:
        for phrase, tag in s.get("tags", {}).items():
            text = text.replace(phrase, f"{tag} {phrase}", 1)
        text = f'{s["tone"]} {text}'
    return text


def elevenlabs(scenes: list[dict]) -> None:
    d = ROOT / "elevenlabs"
    d.mkdir(exist_ok=True)
    lex = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<lexicon version="1.0" xmlns="http://www.w3.org/2005/01/pronunciation-lexicon" alphabet="ipa" xml:lang="en-IN">',
    ]
    lex += [f"  <lexeme><grapheme>{g}</grapheme><alias>{a}</alias></lexeme>" for g, a in ALIASES.items()]
    (d / "pronunciation.pls").write_text("\n".join(lex + ["</lexicon>", ""]))
    (d / "full_multilingual_v2.txt").write_text("\n\n".join(spoken(s, True) for s in scenes).replace("\n\n", '\n<break time="2.5s" />\n') + "\n")
    # one paste for v3/v4: scenes as paragraphs, a long pause between them
    (d / "full.txt").write_text("\n\n[long pause]\n\n".join(spoken(s, False) for s in scenes) + "\n")
    for s in scenes:
        (d / f'{s["id"]}.txt').write_text(spoken(s, False) + "\n")
    md = [
        "# The voiceover for ElevenLabs",
        "",
        "Made by `python video/tools/vo.py` from `video/script.json`; edit that file, not this one.",
        "",
        "## Settings",
        "",
        "- **Model:** Eleven v3 (or v4). It reads the `[tags]` as directions and handles Indian English and the",
        "  pauses (`...`) well. These models ignore `<break>` tags, so the v3/v4 text below has none.",
        "- **Voice:** one Indian English narrator for every scene: calm, warm, 30 to 45 years old. In the Voice",
        '  Library, search "Indian English narration" and pick one that sounds like a person explaining to family,',
        "  not an announcer.",
        "- **Stability:** Natural. **Speed:** 1.0 (0.95 if it rushes). Keep the same voice and settings for all ten.",
        "- **Pronunciation:** add `elevenlabs/pronunciation.pls` (Pronunciation dictionaries) so CBI, OTP, SMS and",
        "  GPay are read as letters.",
        "- **Output:** MP3 44.1 kHz 192 kbps, or WAV if your plan allows.",
        "",
        "## How to generate",
        "",
        "Best: **one generation per scene**. Paste each block below, generate, pick the best of 2 or 3 takes, and",
        "download it as `s01.mp3` … `s10.mp3` (the same text is in `elevenlabs/s01.txt` …). Put the files in",
        "`video/recorded/` and send them to me (or run `npm run build`).",
        "",
        "Also fine: **one take of everything** with Multilingual v2: paste `elevenlabs/full_multilingual_v2.txt`",
        '(it has `<break time="2.5s" />` between scenes), save it as `video/recorded/full.mp3`, and the build',
        "cuts it into scenes at those pauses.",
        "",
        "If a take says a tag out loud, regenerate it; if it keeps happening, delete the tag.",
        "",
    ]
    for s in scenes:
        md += [f'### {s["id"]}: {s["title"]}', "", "```text", spoken(s, False), "```", ""]
    (d / "ELEVENLABS.md").write_text("\n".join(md))


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
    elevenlabs(scenes)
    (ROOT / "public" / "vo").mkdir(parents=True, exist_ok=True)
    split = split_full(scenes)
    t, rows = 0.0, []
    for s in scenes:
        path, recorded = voice(s, split)
        vo = seconds(path)
        dur = max(s["min"], LEAD + vo + TAIL)
        dur = round(dur * FPS) / FPS
        rows.append(
            {
                "id": s["id"],
                "start": round(t, 4),
                "dur": dur,
                "voStart": LEAD,
                "voDur": round(vo, 3),
                "recorded": recorded,
                "anchors": anchors(path, s["vo"], vo),
            }
        )
        print(f'{s["id"]}  {t:6.1f}s  {dur:5.1f}s  voice {vo:4.1f}s  {"recorded" if recorded else "placeholder"}')
        t += dur
    (ROOT / "src" / "timeline.json").write_text(json.dumps({"fps": FPS, "total": round(t, 4), "scenes": rows}, indent=1))
    print(f"total {t:.1f}s")


if __name__ == "__main__":
    main()
