"""Check a voice note the customer shares into the app (e.g. a WhatsApp voice message).

The file is decoded with ffmpeg, scored with S1 and S2 in memory, and deleted. Nothing
is kept unless the customer opts in to training.
"""

from __future__ import annotations

import os
import subprocess
import tempfile

import numpy as np

from engine.config import settings
from engine.fusion import call_s1_score
from engine.signals.s1_synth import detector
from engine.signals.s2_drift import CallDrift, embedder


class VoiceNoteError(Exception):
    pass


def decode_any(data: bytes, sr: int = 16000) -> np.ndarray:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
        f.write(data)
        path = f.name
    try:
        out = subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-i", path, "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
            capture_output=True,
            check=True,
            timeout=60,
        ).stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        raise VoiceNoteError("this file isn't an audio format we can read") from e
    finally:
        os.remove(path)
    return np.frombuffer(out, dtype=np.float32).copy()


def windows_of(x: np.ndarray, win: int = settings.window_samples, hop: int = int(settings.hop_seconds * 16000)) -> list[np.ndarray]:
    if len(x) <= win:
        return [x]
    return [x[i : i + win] for i in range(0, len(x) - win + 1, hop)]


def check(data: bytes) -> dict:
    x = decode_any(data)
    seconds = len(x) / 16000
    if seconds < 1.0:
        return {"verdict": "too_short", "message": "This voice note is too short to check.", "seconds": seconds}
    wins = windows_of(x)
    probs = [r.p_synthetic for r in detector.score(wins)]
    drift = CallDrift()
    for e in embedder.embed(wins):
        drift.update(e)
    s1 = call_s1_score(probs)
    d = drift.max_recent(10)
    drift.wipe()
    if s1 >= settings.red_at:
        verdict, msg = (
            "likely_synthetic",
            "This voice note shows strong signs of a computer-made voice. Please check with the person on their saved number before you pay.",
        )
    elif s1 >= settings.amber_at or (d is not None and d > 0.5):
        verdict, msg = "unsure", "We can't be sure this voice is real. Please check with the person on their saved number before you pay."
    else:
        verdict, msg = "no_signs", "We found no signs of a computer-made voice. Scammers can still pretend to be family, so check before sending money."
    return {
        "verdict": verdict,
        "message": msg,
        "seconds": round(seconds, 1),
        "s1": round(s1, 3),
        "windows": len(wins),
        "max_drift": None if d is None else round(d, 3),
        "model": detector.version,
        "stored": False,
    }
