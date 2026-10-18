"""Phone-line augmentation: what happens to a voice between a mouth and a bank's IVR.

Each channel takes 16 kHz float32 audio and returns 16 kHz float32 audio that has gone
through a real codec (via ffmpeg), so S1 learns phone artefacts and not just lab ones.
"""

from __future__ import annotations

import random
import subprocess

import numpy as np
from scipy.signal import butter, sosfilt

from engine.audio.codec import phone_line, resample

# name -> (encoder args, container, sample rate inside the codec)
CODECS: dict[str, tuple[list[str], str, int]] = {
    "g711a": (["-c:a", "pcm_alaw"], "wav", 8000),
    "amrnb_12k2": (["-c:a", "libopencore_amrnb", "-b:a", "12.2k"], "amr", 8000),
    "amrnb_5k9": (["-c:a", "libopencore_amrnb", "-b:a", "5.9k"], "amr", 8000),
    "amrnb_4k75": (["-c:a", "libopencore_amrnb", "-b:a", "4.75k"], "amr", 8000),
    "gsm": (["-c:a", "libgsm"], "gsm", 8000),
    "ilbc": (["-c:a", "libilbc"], "ilbc", 8000),
    "opus_8k": (["-c:a", "libopus", "-b:a", "8k", "-application", "voip"], "ogg", 8000),
    "opus_12k": (["-c:a", "libopus", "-b:a", "12k", "-application", "voip"], "ogg", 16000),
    "opus_24k": (["-c:a", "libopus", "-b:a", "24k", "-application", "voip"], "ogg", 16000),
}

ALL_CHANNELS = ["clean", "g711u", *CODECS.keys()]
EVAL_CHANNELS = ["clean", "g711u", "amrnb_12k2", "opus_12k"]


def _ffmpeg(x: np.ndarray, args: list[str], fmt: str, rate: int) -> np.ndarray:
    pcm = np.clip(x, -1, 1).astype(np.float32).tobytes()
    enc = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-f", "f32le", "-ar", "16000", "-ac", "1", "-i", "-", "-ar", str(rate), *args, "-f", fmt, "-"],
        input=pcm,
        capture_output=True,
        check=True,
    ).stdout
    dec = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-f", fmt, "-i", "-", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
        input=enc,
        capture_output=True,
        check=True,
    ).stdout
    y = np.frombuffer(dec, dtype=np.float32).copy()
    if len(y) >= len(x):
        return y[: len(x)]
    return np.pad(y, (0, len(x) - len(y)))


def channel(x: np.ndarray, name: str) -> np.ndarray:
    if name == "clean":
        return x.astype(np.float32)
    if name == "g711u":
        return phone_line(x)
    args, fmt, rate = CODECS[name]
    return _ffmpeg(x, args, fmt, rate)


def band_limit(x: np.ndarray, lo: float = 300, hi: float = 3400, sr: int = 16000) -> np.ndarray:
    sos = butter(4, [lo, hi], btype="band", fs=sr, output="sos")
    return sosfilt(sos, x).astype(np.float32)


def packet_loss(x: np.ndarray, rate: float, rng: random.Random, frame: int = 320) -> np.ndarray:
    """Drop 20 ms frames; repeat the previous frame (simple packet-loss concealment)."""
    y = x.copy()
    for i in range(frame, len(y) - frame, frame):
        if rng.random() < rate:
            y[i : i + frame] = y[i - frame : i] * 0.7
    return y


def coloured_noise(x: np.ndarray, snr_db: float, rng: random.Random) -> np.ndarray:
    """RawBoost-style additive noise shaped by a random band-pass filter."""
    n = np.random.default_rng(rng.randrange(1 << 30)).standard_normal(len(x)).astype(np.float32)
    lo = rng.uniform(50, 1500)
    hi = rng.uniform(lo + 500, 7800)
    n = sosfilt(butter(2, [lo, hi], btype="band", fs=16000, output="sos"), n).astype(np.float32)
    px = np.mean(x**2) + 1e-9
    pn = np.mean(n**2) + 1e-9
    return (x + n * np.sqrt(px / (pn * 10 ** (snr_db / 10)))).astype(np.float32)


def random_phone_chain(x: np.ndarray, rng: random.Random) -> tuple[np.ndarray, str]:
    """One random telephony path: optional noise -> codec -> optional loss -> optional band-limit."""
    tags = []
    if rng.random() < 0.4:
        x = coloured_noise(x, rng.uniform(10, 35), rng)
        tags.append("noise")
    name = rng.choice(ALL_CHANNELS[1:]) if rng.random() < 0.85 else "clean"
    x = channel(x, name)
    tags.append(name)
    if rng.random() < 0.3:
        x = packet_loss(x, rng.uniform(0.01, 0.06), rng)
        tags.append("loss")
    if rng.random() < 0.3:
        x = band_limit(x)
        tags.append("band")
    peak = np.max(np.abs(x)) + 1e-9
    x = x / peak * rng.uniform(0.3, 0.95)
    return x.astype(np.float32), "+".join(tags)


def load_audio(path: str, sr: int = 16000) -> np.ndarray:
    import soundfile as sf

    try:
        x, r = sf.read(path, dtype="float32", always_2d=True)
        x = x.mean(axis=1)
        return resample(x, r, sr) if r != sr else x
    except Exception:
        out = subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-i", path, "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
            capture_output=True,
            check=True,
        ).stdout
        return np.frombuffer(out, dtype=np.float32).copy()
