"""Phone-line augmentation: what happens to a voice between a mouth and a bank's IVR.

Each channel takes 16 kHz float32 audio and returns 16 kHz float32 audio that has gone
through a real codec (via ffmpeg), so S1 learns phone artefacts and not just lab ones.

"ota+<codec>" channels add the path a judge's test takes: an AI voice played from a laptop
speaker, across a room, into a phone's microphone and its noise suppressor and AGC, then the
codec (`over_the_air`). Genuine audio in those channels skips the loudspeaker: a real caller
talks into the same phone in the same kind of room, from the mouth to a speakerphone's distance.
"""

from __future__ import annotations

import random
import subprocess

import numpy as np
from scipy.signal import butter, fftconvolve, istft, lfilter, sosfilt, stft

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
# an AI voice played from a speaker into a phone mic (genuine audio: spoken into the same phone)
OTA_CHANNELS = ["ota+g711u", "ota+amrnb_12k2", "ota+g711u+noise"]
# what a cheap phone in a noisy room on a lossy network sounds like, or a fake played over the air
HARD_CHANNELS = ["g711u+loss+noise", "amrnb_12k2+loss+noise", *OTA_CHANNELS]


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


def channel(x: np.ndarray, name: str, seed: int = 0, genuine: bool = False) -> np.ndarray:
    """A fixed phone path. `name` is a codec, optionally with "+noise" (15 dB coloured room
    noise before the codec) and/or "+loss" (3% of 20 ms packets lost after it, concealed),
    e.g. "g711u+loss+noise". An "ota+" prefix puts `over_the_air` before the codec, and then
    "+noise" means a noisy room (8-15 dB at 30 cm) instead. `genuine` only matters for "ota":
    it leaves out the loudspeaker. Deterministic for a given seed, so benchmarks repeat."""
    parts = name.split("+")
    ota = parts[0] == "ota"
    codec, *extras = parts[1:] if ota else parts
    rng = random.Random(seed)
    if ota:
        x = over_the_air(x, rng, loudspeaker=not genuine, noisy="noise" in extras)
    elif "noise" in extras:
        x = coloured_noise(x, 15.0, rng)
    if codec == "clean":
        y = x.astype(np.float32)
    elif codec == "g711u":
        y = phone_line(x)
    else:
        args, fmt, rate = CODECS[codec]
        y = _ffmpeg(x, args, fmt, rate)
    if "loss" in extras:
        y = packet_loss(y, 0.03, rng)
    return y


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


def over_the_air(x: np.ndarray, rng: random.Random, loudspeaker: bool = True, noisy: bool = False, sr: int = 16000) -> np.ndarray:
    """Speaker -> room -> phone mic. With `loudspeaker`, a small speaker 15 cm to 1 m from the phone
    (a laptop on a desk); without it, a talker 3 cm (handset) to 80 cm (speakerphone) away. Then a
    synthetic room (RT60 0.15-0.6 s), room noise whose level against the voice falls with distance
    (20-35 dB at 30 cm, or 8-15 dB when `noisy`), and the phone's own capture chain."""
    g = np.random.default_rng(rng.randrange(1 << 30))
    y = x.astype(np.float64) / (np.max(np.abs(x)) + 1e-9) * 0.5
    if loudspeaker:
        y = small_loudspeaker(y, rng, sr)
        dist = rng.uniform(0.15, 1.0)
    else:
        dist = rng.uniform(0.03, 0.8)
    y = fftconvolve(y, room_ir(rng.uniform(0.15, 0.6), dist, rng, g, sr))[: len(x)]
    snr = (rng.uniform(8, 15) if noisy else rng.uniform(20, 35)) - 20 * np.log10(dist / 0.3)
    n = room_noise(len(y), rng, g, sr)
    py, pn = np.mean(y**2) + 1e-12, np.mean(n**2) + 1e-12
    y = y + n * np.sqrt(py / (pn * 10 ** (min(snr, 45.0) / 10)))
    return phone_mic(y, rng, sr).astype(np.float32)


def peaking(x: np.ndarray, f0: float, gain_db: float, q: float, sr: int = 16000) -> np.ndarray:
    """RBJ peaking-EQ biquad: a resonance (gain > 0) or a dip."""
    amp = 10 ** (gain_db / 40)
    w0 = 2 * np.pi * f0 / sr
    al = np.sin(w0) / (2 * q)
    b = [1 + al * amp, -2 * np.cos(w0), 1 - al * amp]
    a = [1 + al / amp, -2 * np.cos(w0), 1 - al / amp]
    return lfilter(b, a, x)


def small_loudspeaker(x: np.ndarray, rng: random.Random, sr: int = 16000) -> np.ndarray:
    """A laptop or phone speaker: an amplifier that soft-clips (with a little even-order
    distortion), no bass below 250-400 Hz, two or three cone/cavity resonances and a dip, and
    a top end that rolls off at 5.5-7.5 kHz."""
    drive = rng.uniform(1.2, 3.0)
    y = np.tanh(drive * x) / np.tanh(drive)
    y = y + rng.uniform(0.0, 0.08) * y**2
    y = y - np.mean(y)
    y = sosfilt(butter(rng.choice([2, 4]), rng.uniform(250, 400), btype="high", fs=sr, output="sos"), y)
    for _ in range(rng.randint(2, 3)):
        y = peaking(y, float(np.exp(rng.uniform(np.log(500), np.log(6000)))), rng.uniform(3, 9), rng.uniform(1.5, 5), sr)
    y = peaking(y, float(np.exp(rng.uniform(np.log(800), np.log(5000)))), -rng.uniform(3, 8), rng.uniform(1, 3), sr)
    return sosfilt(butter(4, rng.uniform(5500, 7500), btype="low", fs=sr, output="sos"), y)


def room_ir(rt60: float, dist: float, rng: random.Random, g: np.random.Generator, sr: int = 16000) -> np.ndarray:
    """A synthetic room impulse response: the direct path, 4-8 early reflections within 20 ms,
    and an exponentially decaying diffuse tail whose highs die faster than its lows. The tail's
    energy sets the direct-to-reverberant ratio from the room's critical distance
    (0.057 * sqrt(V / RT60) for a 20-90 m^3 room)."""
    n = int(min(1.2 * rt60, 1.0) * sr)
    d0 = int(dist / 343 * sr)
    t = np.arange(n) / sr
    lo = sosfilt(butter(2, 1500, btype="low", fs=sr, output="sos"), g.standard_normal(n)) * np.exp(-6.9078 * t / rt60)
    hi = sosfilt(butter(2, 1500, btype="high", fs=sr, output="sos"), g.standard_normal(n)) * np.exp(-6.9078 * t / (0.6 * rt60))
    tail = (lo + hi) * np.clip((t - 0.002) / 0.01, 0, 1)  # the diffuse field builds up over ~10 ms
    for _ in range(rng.randint(4, 8)):
        k = int(rng.uniform(0.001, 0.02) * sr)
        tail[k] += rng.choice([-1, 1]) * rng.uniform(0.3, 0.8) * dist / (dist + 343 * k / sr)
    dc = 0.057 * np.sqrt(rng.uniform(20, 90) / rt60)
    tail *= np.sqrt((dist / dc) ** 2 / (np.sum(tail**2) + 1e-12))
    h = np.zeros(d0 + n)
    h[d0] = 1.0
    h[d0:] += tail
    return h


def room_noise(n: int, rng: random.Random, g: np.random.Generator, sr: int = 16000) -> np.ndarray:
    """Pink background noise (fans, traffic, air conditioning), sometimes with 50 Hz mains hum."""
    spec = np.fft.rfft(g.standard_normal(n))
    spec /= np.sqrt(np.maximum(np.fft.rfftfreq(n, 1 / sr), 20.0))
    y = np.fft.irfft(spec, n)
    y /= np.std(y) + 1e-12
    if rng.random() < 0.3:
        t = np.arange(n) / sr
        y += sum(rng.uniform(0.1, 0.5) / k * np.sin(2 * np.pi * 50 * k * t + rng.uniform(0, 6.3)) for k in (1, 2, 3))
    return y


def phone_mic(x: np.ndarray, rng: random.Random, sr: int = 16000) -> np.ndarray:
    """What a phone does to its mic signal in a call: the capsule's low cut, a spectral noise
    suppressor (Wiener-style gains against a quantile noise floor, smoothed over time, which
    leaves the usual musical-noise and onset artefacts), then AGC towards -20 dBFS and a limiter.
    No echo canceller: with no far-end audio playing it passes the signal through."""
    y = sosfilt(butter(2, rng.uniform(80, 150), btype="high", fs=sr, output="sos"), x)
    _, _, z = stft(y, fs=sr, nperseg=512, noverlap=384)
    p = np.abs(z) ** 2
    noise = np.quantile(p, rng.uniform(0.05, 0.2), axis=1, keepdims=True)
    gain = np.maximum(1 - rng.uniform(1.0, 2.5) * noise / (p + 1e-12), 10 ** (-rng.uniform(10, 25) / 20))
    alpha = rng.uniform(0.5, 0.85)
    gain = lfilter([1 - alpha], [1, -alpha], gain, axis=1)
    _, y = istft(z * gain, fs=sr, nperseg=512, noverlap=384)
    y = np.pad(y, (0, max(0, len(x) - len(y))))[: len(x)]
    block = sr // 100  # AGC on 10 ms blocks: fast attack, slow release, at most +30 dB
    rms = np.sqrt(np.mean(np.pad(y, (0, -len(y) % block)).reshape(-1, block) ** 2, axis=1)) + 1e-6
    want = np.clip(0.1 / rms, 10 ** (-10 / 20), 10 ** (30 / 20))
    gain, level = np.empty_like(want), want[0]
    for i, w in enumerate(want):
        level += (w - level) * (0.6 if w < level else 0.03)
        gain[i] = level
    y = y * np.repeat(gain, block)[: len(y)]
    return 0.95 * np.tanh(y / 0.95)


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
