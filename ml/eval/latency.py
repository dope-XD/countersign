"""S1 latency as the live engine sees it: one 4 s window at a time, on this machine.

    python -m ml.eval.latency --checkpoint models/s1_add_w2vlarge.pt [--n 200]

Prints p50/p95/max in ms per window (target: p95 <= 300 ms on the demo laptop's GPU).
"""

from __future__ import annotations

import argparse
import json
import time

import numpy as np

from engine.config import settings
from engine.signals.s1_synth import S1Detector


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--n", type=int, default=200)
    a = ap.parse_args()
    det = S1Detector()
    det.load(a.checkpoint)
    rng = np.random.default_rng(0)
    ms = []
    for _ in range(a.n):
        w = (rng.standard_normal(settings.window_samples) * 0.1).astype(np.float32)
        t0 = time.perf_counter()
        det.score([w])
        ms.append((time.perf_counter() - t0) * 1000)
    out = {
        "model": det.version,
        "device": det.device,
        "n": a.n,
        "p50_ms": round(float(np.percentile(ms, 50)), 1),
        "p95_ms": round(float(np.percentile(ms, 95)), 1),
        "max_ms": round(float(np.max(ms)), 1),
    }
    print(json.dumps(out))


if __name__ == "__main__":
    main()
