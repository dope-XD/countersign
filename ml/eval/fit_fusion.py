"""Fit the fusion weights on an IndiaCall *dev* run, then check them on a separate test run.

    python -m ml.eval.fit_fusion --dev dev            # reads models/eval/indiacall_dev.json
    -> models/fusion.json  (restart the engine to load it)

Logistic regression on the same features the engine computes (x1 = logit S1 call score,
x2 = drift excess, x3 = liveness failure) with genuine = 0, attack = 1. The bias is then
shifted so that at most 5% of genuine dev calls reach AMBER (deck target).
"""

from __future__ import annotations

import argparse
import json
import math

import numpy as np
from sklearn.linear_model import LogisticRegression

from engine.config import settings
from engine.fusion import FusionWeights, features

EVAL = settings.models_dir / "eval"


def call_features(r: dict, w: FusionWeights) -> list[float] | None:
    """Rebuild the engine's fusion features from a simulated call's result."""
    f = r.get("features")
    if not f or f.get("s1") is None:
        return None
    # the engine reports the call-level S1 score, which is all x1 needs
    return list(features([f["s1"]], f.get("drift"), r.get("liveness"), w))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev", default="dev")
    ap.add_argument("--max-genuine-amber", type=float, default=0.05)
    a = ap.parse_args()
    base = FusionWeights()
    rows = [r for r in json.loads((EVAL / f"indiacall_{a.dev}.json").read_text())["results"] if not r.get("error")]
    X, y = [], []
    for r in rows:
        f = call_features(r, base)
        if f is not None:
            X.append(f)
            y.append(0 if r["plan"]["level"] == "genuine" else 1)
    X, y = np.array(X), np.array(y)
    if len(set(y)) < 2:
        raise SystemExit("need both genuine and attack calls in the dev run")
    clf = LogisticRegression(C=1.0, class_weight="balanced").fit(X, y)
    w1, w2, w3 = (float(v) for v in clf.coef_[0])
    b = float(clf.intercept_[0])
    # shift the bias so genuine dev calls stay under the AMBER cut-off
    z = X[y == 0] @ np.array([w1, w2, w3]) + b
    amber_logit = math.log(settings.amber_at / (1 - settings.amber_at))
    q = float(np.quantile(z, 1 - a.max_genuine_amber)) if len(z) else 0.0
    if q > amber_logit:
        b -= q - amber_logit + 1e-3
    zr = X @ np.array([w1, w2, w3]) + b
    r = 1 / (1 + np.exp(-zr))
    gen_amber = float(np.mean(r[y == 0] >= settings.amber_at))
    att_red = float(np.mean(r[y == 1] >= settings.red_at))
    out = {
        "w1": max(w1, 0.1),
        "w2": max(w2, 0.0),
        "w3": max(w3, 0.0),
        "b": b,
        "drift_threshold": base.drift_threshold,
        "drift_scale": base.drift_scale,
        "source": f"fitted on IndiaCall run '{a.dev}' ({len(y)} calls)",
        "dev_genuine_amber_or_red": gen_amber,
        "dev_attack_red": att_red,
    }
    (settings.models_dir / "fusion.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
