"""An original score and sound effects for the video, synthesised from scratch and timed to src/timeline.json.

    .venv/bin/python video/music/make_music.py     # writes video/public/audio/music.wav and sfx_*.wav

96 BPM. The dark act (the scam call) is A minor: a low drone, a muted pulse, a ticking hat, and a riser into the cut
to the logo. The logo lands on an impact and the key lifts to C major: warm pads (Am-F-C-G), a plucked arpeggio and
a soft kick; bass and a light clap join for the research and the results; "what it still misses" drops back to pads;
the end resolves on C with a chime. Every sound is sine, saw or noise with envelopes, a filter and a synthetic reverb.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, fftconvolve, sosfilt

ROOT = Path(__file__).resolve().parents[1]
SR = 48000
BPM = 96
BEAT = 60 / BPM
rng = np.random.default_rng(7)


def hz(note: str) -> float:
    names = {"C": -9, "C#": -8, "D": -7, "D#": -6, "E": -5, "F": -4, "F#": -3, "G": -2, "G#": -1, "A": 0, "A#": 1, "B": 2}
    n, o = note[:-1], int(note[-1])
    return 440.0 * 2 ** ((names[n] + 12 * (o - 4)) / 12)


def t_(dur: float) -> np.ndarray:
    return np.arange(int(dur * SR)) / SR


def env(n: int, a: float, r: float, curve: float = 1.0) -> np.ndarray:
    """Attack a, release r (seconds), sustain between."""
    e = np.ones(n)
    na, nr = min(n, int(a * SR)), min(n, int(r * SR))
    if na:
        e[:na] = np.linspace(0, 1, na) ** curve
    if nr:
        e[n - nr :] *= np.linspace(1, 0, nr) ** curve
    return e


def decay(n: int, tau: float) -> np.ndarray:
    return np.exp(-np.arange(n) / SR / tau)


def lp(x: np.ndarray, f: float, order: int = 2) -> np.ndarray:
    return sosfilt(butter(order, min(f, SR / 2 - 100), "low", fs=SR, output="sos"), x)


def hp(x: np.ndarray, f: float, order: int = 2) -> np.ndarray:
    return sosfilt(butter(order, f, "high", fs=SR, output="sos"), x)


def bp(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    return sosfilt(butter(2, [lo, hi], "band", fs=SR, output="sos"), x)


def saw(f: float, tt: np.ndarray) -> np.ndarray:
    # band-limited enough for pads once low-passed
    ph = (f * tt) % 1.0
    return 2 * ph - 1


def reverb(x: np.ndarray, secs: float = 2.6, wet: float = 0.3) -> np.ndarray:
    n = int(secs * SR)
    ir = rng.standard_normal(n) * decay(n, secs / 6.5)
    ir = lp(ir, 6000)
    ir /= np.sqrt(np.sum(ir**2))
    return x * (1 - wet) + fftconvolve(x, ir)[: len(x)] * wet * 1.6


class Track:
    def __init__(self, dur: float):
        self.x = np.zeros(int(dur * SR) + SR * 4)

    def add(self, at: float, sig: np.ndarray, gain: float = 1.0):
        i = int(at * SR)
        if i < 0:
            sig, i = sig[-i:], 0
        j = min(len(self.x), i + len(sig))
        self.x[i:j] += sig[: j - i] * gain


# ---------- voices ----------


def pad(notes: list[str], dur: float, cutoff: float = 1800) -> np.ndarray:
    tt = t_(dur)
    s = np.zeros_like(tt)
    for n in notes:
        f = hz(n)
        for cents in (-7, 0, 7):
            s += saw(f * 2 ** (cents / 1200), tt + rng.random())
    s = lp(s, cutoff, 2) / (len(notes) * 3)
    return s * env(len(tt), min(1.6, dur / 3), min(2.0, dur / 2.5), 1.5)


def pluck(note: str, dur: float = 0.6) -> np.ndarray:
    tt = t_(dur)
    f = hz(note)
    s = np.sin(2 * np.pi * f * tt) + 0.35 * np.sin(4 * np.pi * f * tt) + 0.12 * np.sin(6 * np.pi * f * tt)
    return s * decay(len(tt), 0.16) * env(len(tt), 0.004, 0.05)


def kick(gain: float = 1.0) -> np.ndarray:
    tt = t_(0.42)
    f = 45 + 85 * np.exp(-tt / 0.045)
    s = np.sin(2 * np.pi * np.cumsum(f) / SR) * decay(len(tt), 0.13)
    click = hp(rng.standard_normal(len(tt)), 3000) * decay(len(tt), 0.003) * 0.25
    return (s + click) * gain


def hat(gain: float = 1.0, tau: float = 0.025) -> np.ndarray:
    n = int(0.12 * SR)
    return hp(rng.standard_normal(n), 7000, 4) * decay(n, tau) * gain


def clap() -> np.ndarray:
    n = int(0.3 * SR)
    s = bp(rng.standard_normal(n), 900, 3500)
    e = np.zeros(n)
    for k, d in enumerate((0, 0.011, 0.022)):
        i = int(d * SR)
        e[i:] += decay(n - i, 0.012 if k < 2 else 0.09)
    return s * e * 0.5


def bass(note: str, dur: float) -> np.ndarray:
    tt = t_(dur)
    f = hz(note)
    s = np.sin(2 * np.pi * f * tt) + 0.4 * lp(saw(f, tt), 400)
    return s * env(len(tt), 0.01, 0.08) * decay(len(tt), 0.5)


def pulse(note: str) -> np.ndarray:
    tt = t_(0.35)
    f = hz(note)
    s = lp(saw(f, tt) + 0.5 * saw(f * 1.005, tt), 420)
    return s * decay(len(tt), 0.09)


def bell(note: str, dur: float = 2.5) -> np.ndarray:
    tt = t_(dur)
    f = hz(note)
    s = sum(a * np.sin(2 * np.pi * f * m * tt) * decay(len(tt), dur / (1 + m)) for m, a in ((1, 1), (2.76, 0.35), (5.4, 0.18), (8.9, 0.08)))
    return s * env(len(tt), 0.002, 0.2)


def noise_riser(dur: float) -> np.ndarray:
    n = int(dur * SR)
    s = rng.standard_normal(n)
    out = np.zeros(n)
    k = 8
    for i in range(k):  # a sweep in steps: band-pass rising from 300 Hz to 6 kHz
        a, b = i * n // k, (i + 1) * n // k
        lo = 300 * (20 ** (i / k))
        out[a:b] = bp(s, lo, lo * 2.2)[a:b]
    return out * np.linspace(0, 1, n) ** 2.2


def boom() -> np.ndarray:
    tt = t_(2.4)
    f = 32 + 40 * np.exp(-tt / 0.12)
    s = np.sin(2 * np.pi * np.cumsum(f) / SR) * decay(len(tt), 0.7)
    s += lp(rng.standard_normal(len(tt)), 2500) * decay(len(tt), 0.08) * 0.6
    return s


# ---------- the score ----------


def score(tl: dict) -> np.ndarray:
    sc = {s["id"]: s for s in tl["scenes"]}
    total = tl["total"]
    lift = sc["s04"]["start"]
    research = sc["s07"]["start"]
    misses = sc["s09"]["start"]
    end = sc["s10"]["start"]
    tr = Track(total)
    music = Track(total)  # what gets reverb

    # dark act: drone, pulse, hat
    drone = pad(["A1", "E2", "A2"], lift + 1.0, cutoff=380)
    music.add(0, hp(drone, 45), 0.42)
    music.add(0, pad(["C3", "E3", "A3"], lift, cutoff=700), 0.25)
    t = 2 * BEAT * 4  # the pulse comes in after two bars
    while t < lift - 0.2:
        b = round(t / BEAT * 2) % 16
        tr.add(t, pulse("A1" if b % 8 else "A2"), 0.32 if b % 4 == 0 else 0.18)
        if t > sc["s02"]["start"]:
            tr.add(t, hat(0.12 if b % 2 else 0.05))
        t += BEAT / 2
    tr.add(lift - 3.2, noise_riser(3.2), 0.22)
    rt = t_(3.2)
    tr.add(lift - 3.2, np.sin(2 * np.pi * np.cumsum(110 * 2 ** (rt / 3.2 * 2)) / SR) * np.linspace(0, 1, len(rt)) ** 3, 0.08)

    # the logo: impact and the lift
    tr.add(lift, boom(), 0.9)
    tr.add(lift, bell("C6", 3.0), 0.12)

    chords = [["A2", "C4", "E4", "A4"], ["F2", "A3", "C4", "F4"], ["C3", "E4", "G4", "C5"], ["G2", "B3", "D4", "G4"]]
    roots = ["A1", "F1", "C2", "G1"]
    arps = [["A4", "C5", "E5", "C5"], ["F4", "A4", "C5", "A4"], ["G4", "C5", "E5", "C5"], ["G4", "B4", "D5", "B4"]]
    bar = 4 * BEAT
    t, k = lift, 0
    while t < end:
        ci = k % 4
        span = 2 * bar
        music.add(t, pad(chords[ci], span + 1.2, cutoff=2400), 0.62)
        drums = t >= lift + bar and not (misses <= t < misses + 8 * BEAT * 2)
        full = research <= t < misses
        for step in range(16):  # eighth notes over two bars
            s = t + step * BEAT / 2
            if s >= end:
                break
            if s > lift + bar / 2:
                music.add(s, pluck(arps[ci][step % 4] if step % 8 < 6 else arps[ci][(step + 2) % 4]), 0.16 if full else 0.12)
            if drums and step % 4 == 0:
                tr.add(s, kick(0.55))
            if drums and step % 2 == 1:
                tr.add(s, hat(0.08))
            if full and step % 8 == 4:
                tr.add(s, clap(), 0.35)
            if full and step % 2 == 0:
                tr.add(s, bass(roots[ci], BEAT / 2 * 0.95), 0.33)
        t += span
        k += 1

    # the end: resolve on C, chime, tail
    music.add(end, pad(["C2", "G3", "C4", "E4", "G4", "B4", "D5"], total - end + 1, cutoff=2600), 0.55)
    tr.add(end, boom(), 0.35)
    for i, n in enumerate(["C6", "G5", "E6"]):
        music.add(end + 0.4 + i * 0.35, bell(n, 3.5), 0.11)

    mix = tr.x + reverb(music.x, 2.8, 0.32)
    mix = hp(mix, 28)
    mix = mix[: int(total * SR)]
    fade = np.ones_like(mix)
    fade[-int(2.5 * SR) :] = np.linspace(1, 0, int(2.5 * SR)) ** 1.5
    return mix * fade


# ---------- sound effects ----------


def sfx() -> dict[str, np.ndarray]:
    out: dict[str, np.ndarray] = {}
    # a phone ringing: two short bursts of 400 + 450 Hz, twice
    r = np.zeros(int(2.4 * SR))
    for start in (0.0, 0.6):
        tt = t_(0.4)
        burst = (np.sin(2 * np.pi * 400 * tt) + np.sin(2 * np.pi * 450 * tt)) * env(len(tt), 0.01, 0.03)
        i = int(start * SR)
        r[i : i + len(burst)] += burst * 0.4
    out["ring"] = r
    clicks = np.zeros(int(1.4 * SR))
    for k in range(18):
        i = int((k * 0.075 + rng.random() * 0.02) * SR)
        c = bp(rng.standard_normal(int(0.02 * SR)), 2000, 6000) * decay(int(0.02 * SR), 0.003)
        clicks[i : i + len(c)] += c * (0.6 + 0.4 * rng.random())
    out["type"] = clicks
    out["tick"] = bp(rng.standard_normal(int(0.05 * SR)), 1500, 5000) * decay(int(0.05 * SR), 0.006)
    n = int(0.7 * SR)
    w = rng.standard_normal(n)
    out["whoosh"] = (lp(w, 1200) * 0.6 + bp(w, 2000, 5000) * 0.25) * np.sin(np.linspace(0, np.pi, n)) ** 2
    tt = t_(0.18)
    out["tap"] = (
        np.sin(2 * np.pi * (180 + 300 * np.exp(-tt / 0.01)) * tt) * decay(len(tt), 0.03) + out["tick"][: len(tt)] * 0.5
        if len(out["tick"]) >= len(tt)
        else np.sin(2 * np.pi * 220 * tt) * decay(len(tt), 0.03)
    )
    out["amber"] = np.concatenate([bell("A5", 0.25)[: int(0.18 * SR)], bell("F5", 1.4)]) * 0.5
    beeps = np.zeros(int(1.2 * SR))
    for k in range(3):
        tt = t_(0.14)
        b = lp(np.sign(np.sin(2 * np.pi * 880 * tt)), 2500) * env(len(tt), 0.005, 0.03)
        i = int(k * 0.22 * SR)
        beeps[i : i + len(b)] += b * 0.35
    out["alarm"] = beeps
    out["impact"] = boom() * 0.9
    tt = t_(0.09)
    out["pop"] = np.sin(2 * np.pi * np.cumsum(300 + 500 * tt / 0.09) / SR) * decay(len(tt), 0.03)
    out["clear"] = np.concatenate([bell("C6", 0.22)[: int(0.16 * SR)], bell("G6", 1.5)]) * 0.5
    out["rise"] = noise_riser(1.0) * 0.6
    tt = t_(0.7)
    out["down"] = np.sin(2 * np.pi * np.cumsum(900 * np.exp(-tt / 0.25) + 120) / SR) * decay(len(tt), 0.25) * 0.5
    return out


def write(path: Path, x: np.ndarray, peak: float = 0.89):
    x = x / (np.max(np.abs(x)) + 1e-9) * peak
    st = np.stack([x, x], axis=1)
    wavfile.write(path, SR, (st * 32767).astype(np.int16))


def main():
    tl = json.loads((ROOT / "src" / "timeline.json").read_text())
    out = ROOT / "public" / "audio"
    out.mkdir(parents=True, exist_ok=True)
    m = score(tl)
    # gentle stereo: a short delay on one side for width
    write(out / "music.wav", m)
    for name, x in sfx().items():
        write(out / f"sfx_{name}.wav", x, 0.8)
    print(f"music {len(m) / SR:.1f}s, {len(sfx())} effects -> {out}")


if __name__ == "__main__":
    main()
