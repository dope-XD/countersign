"""Run the spot-check kit (or any folder of recordings and messages) through the phone's own pipeline, on a laptop CPU.

    python -m ml.eval.kit data/kit             # our kit, with its expected.csv: a pass/fail table in a few minutes
    python -m ml.eval.kit /path/to/jury/folder # any folder: .wav/.mp3/.m4a/.ogg/.flac/.amr recordings and .txt messages

The same model files the phone ships: Silero VAD + Omnilingual speech-to-text (sherpa-onnx), the cue rules, our
classifier and fusion (assets/), and the voice-clone model (ONNX). A recording gets two answers: what the words say
(cues + classifier, as on "Check a recording") and whether the voice sounds AI-made. Reproducibility only: on the
phone this all runs on the phone.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import numpy as np

from engine.listener.analyzer import analyze_text

ROOT = Path(__file__).resolve().parents[2]
AUDIO = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".amr", ".aac", ".opus", ".webm"}


def load_audio(p: Path) -> np.ndarray:
    import subprocess

    import soundfile as sf

    from engine.audio.codec import resample

    try:
        x, sr = sf.read(str(p), dtype="float32", always_2d=False)
    except Exception:
        raw = subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-i", str(p), "-ac", "1", "-ar", "16000", "-f", "f32le", "-"], capture_output=True, check=True
        ).stdout
        return np.frombuffer(raw, dtype=np.float32)
    x = x.mean(axis=1) if x.ndim > 1 else x
    return resample(x, sr, 16000).astype(np.float32)


class Phone:
    """The phone's pipeline: VAD → speech-to-text → Analyzer, and the voice check."""

    def __init__(self) -> None:
        from ml.eval import asr_bakeoff

        self.asr = asr_bakeoff.recognizer("omnilingual_300m")
        self.bakeoff = asr_bakeoff
        self.voice = None
        self.voice_meta = None
        v = ROOT / "models" / "voice_clone" / "voice.int8.onnx"
        if v.exists():
            import onnxruntime as ort

            self.voice = ort.InferenceSession(str(v), providers=["CPUExecutionProvider"])
            self.voice_meta = json.loads((v.parent / "voice.json").read_text(encoding="utf-8"))

    def transcribe(self, x: np.ndarray) -> str:
        return self.bakeoff.decode(self.asr, self.bakeoff.vad_segments(x))

    def voice_score(self, x: np.ndarray) -> float | None:
        if self.voice is None or len(x) < 32000:
            return None
        y = x[: self.voice_meta.get("seconds", 20) * 16000].astype(np.float32)
        y = (y - y.mean()) / max(float(y.std()), 1e-5)  # as VoiceCheck.kt
        out = self.voice.run(None, {self.voice.get_inputs()[0].name: y[None, :]})[0]
        return float(np.asarray(out).reshape(-1)[-1])


def run(folder: Path) -> list[dict]:
    expected = {}
    if (folder / "expected.csv").exists():
        with open(folder / "expected.csv", encoding="utf-8") as fh:
            expected = {r["file"]: r for r in csv.DictReader(fh)}
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in AUDIO | {".txt"})
    phone = Phone() if any(p.suffix.lower() in AUDIO for p in files) else None
    out = []
    for p in files:
        t0 = time.time()
        if p.suffix.lower() == ".txt":
            text, voice, secs = p.read_text(encoding="utf-8").strip(), None, 0.0
            a = analyze_text(text)
        else:
            x = load_audio(p)
            text, secs = phone.transcribe(x), len(x) / 16000
            voice = phone.voice_score(x)
            a = analyze_text(text, min_words=12)  # the words alone, as the phone's "what the words say"
        thr = phone.voice_meta["threshold"] if phone and phone.voice_meta else 0.5
        e = expected.get(p.name, {})
        want = e.get("expect")
        if want in ("scam", "harmless"):
            ok = (a.level in ("warn", "scam")) == (want == "scam")
        elif want in ("ai", "real"):
            ok = None if voice is None else (voice >= thr) == (want == "ai")
        else:
            ok = None
        out.append({
            "file": p.name, "kind": e.get("kind", "text" if p.suffix == ".txt" else "recording"), "expect": want or "?",
            "level": a.level, "type": a.type, "why": a.cues[:4], "p_scam": None if a.p_scam is None else round(a.p_scam, 3),
            "voice_ai": None if voice is None else round(voice, 3), "pass": ok, "seconds": round(secs, 1), "took_s": round(time.time() - t0, 2),
            "heard": text[:160],
        })  # fmt: skip
    return out


def table(rows: list[dict]) -> str:
    L = ["| File | Kind | Expected | Phone says | Why | Voice AI | Pass |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        says = f"{r['level']}" + (f" ({r['type']})" if r["level"] in ("warn", "scam") else "")
        mark = {True: "✓", False: "✗", None: "–"}[r["pass"]]
        v = "–" if r["voice_ai"] is None else f"{r['voice_ai']:.2f}"
        L.append(f"| {r['file']} | {r['kind']} | {r['expect']} | {says} | {', '.join(r['why']) or '–'} | {v} | {mark} |")
    judged = [r for r in rows if r["pass"] is not None]
    L.append("")
    L.append(
        f"**{sum(r['pass'] for r in judged)}/{len(judged)} passed**"
        + (f" ({len(rows) - len(judged)} without an expected answer)" if len(judged) < len(rows) else "")
    )
    for k in ("text", "call", "voice"):
        ks = [r for r in judged if r["kind"] == k]
        if ks:
            L.append(f"- {k}: {sum(r['pass'] for r in ks)}/{len(ks)}")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("--json", type=Path, help="also write the rows here")
    a = ap.parse_args()
    t0 = time.time()
    rows = run(a.folder)
    print(table(rows))
    print(f"\n{len(rows)} items in {time.time() - t0:.0f} s on CPU", file=sys.stderr)
    out = a.json or (ROOT / "models" / "eval" / "kit.json" if a.folder.resolve() == (ROOT / "data" / "kit").resolve() else None)
    if out:
        out.write_text(json.dumps({"rows": rows, "markdown": table(rows)}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
