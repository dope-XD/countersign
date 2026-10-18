"""EER, detection rate at a fixed false-alarm rate, and Wilson intervals."""

from __future__ import annotations

import math

import numpy as np


def eer(bona_scores: np.ndarray, spoof_scores: np.ndarray) -> tuple[float, float]:
    """Scores are P(spoof): higher = more likely fake. Returns (eer, threshold)."""
    bona = np.asarray(bona_scores, dtype=np.float64)
    spoof = np.asarray(spoof_scores, dtype=np.float64)
    thr = np.unique(np.concatenate([bona, spoof]))
    # false accept: spoof scored below threshold; false reject: bona scored at/above threshold
    spoof_sorted = np.sort(spoof)
    bona_sorted = np.sort(bona)
    far = np.searchsorted(spoof_sorted, thr, side="left") / len(spoof)
    frr = 1 - np.searchsorted(bona_sorted, thr, side="left") / len(bona)
    i = int(np.argmin(np.abs(far - frr)))
    return float((far[i] + frr[i]) / 2), float(thr[i])


def detection_at_far(bona_scores, spoof_scores, false_alarm: float = 0.01) -> tuple[float, float]:
    """Share of spoofs caught when at most `false_alarm` of genuine audio is flagged."""
    bona = np.sort(np.asarray(bona_scores))
    t = float(np.quantile(bona, 1 - false_alarm))
    return float(np.mean(np.asarray(spoof_scores) > t)), t


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, (c - m) / d), min(1.0, (c + m) / d))
