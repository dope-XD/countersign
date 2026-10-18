"""Replay detection: has this audio been heard in a confirmed fraud case before?

Landmark fingerprinting (the idea behind Shazam), sized for 8 kHz phone audio:
spectral peaks are paired into hashes (f1, f2 - f1, dt), and a match needs many hashes
that agree on the *same* time offset. That survives codecs, gain changes and the clip
starting at a different point, which an exact hash never would. Only these integers are
stored, never the audio.
"""

from __future__ import annotations

import threading
from collections import Counter, defaultdict

import numpy as np
from scipy.ndimage import maximum_filter
from scipy.signal import stft

from engine.db import db

SR = 8000
N_FFT = 512  # 64 ms
HOP = 128  # 16 ms
F_LO, F_HI = 19, 218  # bins for ~300-3400 Hz, the phone band
PEAK_NEIGHBOURHOOD = (15, 9)  # (freq bins, frames)
PEAKS_PER_SECOND = 30
FAN_OUT = 6
DT_MAX = 40  # frames (~640 ms)
DF_MAX = 63
MIN_VOTES = 12  # hashes agreeing on one offset
MIN_RATIO = 0.04  # ...as a share of the query's hashes


def _peaks(x: np.ndarray) -> list[tuple[int, int]]:
    """(frame, bin) of prominent spectral peaks, strongest first per second of audio."""
    if len(x) < N_FFT * 2:
        return []
    _, _, z = stft(x, fs=SR, nperseg=N_FFT, noverlap=N_FFT - HOP, boundary=None, padded=False)
    s = np.log(np.abs(z[F_LO:F_HI]) + 1e-6)
    local = maximum_filter(s, size=PEAK_NEIGHBOURHOOD, mode="constant", cval=-np.inf)
    mask = (s == local) & (s > np.median(s) + 1.0)
    f, t = np.nonzero(mask)
    if not len(t):
        return []
    keep = int(PEAKS_PER_SECOND * len(x) / SR)
    order = np.argsort(-s[f, t])[:keep]
    pts = sorted(zip(t[order].tolist(), (f[order] + F_LO).tolist(), strict=False))
    return pts


def landmarks(x8k: np.ndarray) -> list[tuple[int, int]]:
    """[(hash, anchor_frame)] for 8 kHz audio."""
    pts = _peaks(np.asarray(x8k, dtype=np.float32))
    out = []
    for i, (t1, f1) in enumerate(pts):
        n = 0
        for t2, f2 in pts[i + 1 :]:
            dt = t2 - t1
            if dt > DT_MAX:
                break
            df = f2 - f1
            if dt < 1 or abs(df) > DF_MAX:
                continue
            out.append(((f1 << 14) | ((df + DF_MAX) << 7) | dt, t1))
            n += 1
            if n >= FAN_OUT:
                break
    return out


class ReplayIndex:
    """Landmarks of confirmed-fraud clips, in memory, persisted in SQLite."""

    def __init__(self):
        self._lock = threading.Lock()
        self._index: dict[int, list[tuple[str, int]]] | None = None

    def _load(self) -> dict[int, list[tuple[str, int]]]:
        if self._index is None:
            idx: dict[int, list[tuple[str, int]]] = defaultdict(list)
            for r in db.query("SELECT hash, case_id, t FROM replay_landmarks"):
                idx[r["hash"]].append((r["case_id"], r["t"]))
            self._index = idx
        return self._index

    def add(self, case_id: str, x8k: np.ndarray) -> int:
        lm = landmarks(x8k)
        with self._lock:
            idx = self._load()
            db.executemany("INSERT INTO replay_landmarks (hash, case_id, t) VALUES (?,?,?)", [(h, case_id, t) for h, t in lm])
            for h, t in lm:
                idx[h].append((case_id, t))
        return len(lm)

    def matches(self, x8k: np.ndarray) -> str | None:
        """Case id whose clip this audio replays, or None."""
        with self._lock:
            idx = self._load()
            if not idx:
                return None
            lm = landmarks(x8k)
            votes: Counter = Counter()
            for h, t in lm:
                for case_id, t_ref in idx.get(h, ()):
                    votes[(case_id, t_ref - t)] += 1
        if not votes:
            return None
        (case_id, _offset), n = votes.most_common(1)[0]
        return case_id if n >= MIN_VOTES and n >= MIN_RATIO * len(lm) else None

    def clear(self) -> None:
        with self._lock:
            db.execute("DELETE FROM replay_landmarks")
            self._index = None


replay_index = ReplayIndex()
