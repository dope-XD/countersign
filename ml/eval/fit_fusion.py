"""Fit the fusion on an IndiaCall *dev* run, then check it on a separate test run.

    python -m ml.eval.fit_fusion --dev dev            # reads models/eval/indiacall_dev.json
    -> models/fusion.json  (restart the engine to load it)

Three things are fitted, in this order:
1. drift_threshold: the 99th percentile of S2 drift on genuine dev calls (the default is kept,
   and said so, when the run has no drift values, e.g. S2 was off).
2. w1-w3 and b: logistic regression on the features the engine computes (x1 = logit S1 call
   score, x2 = drift excess over the fitted threshold, x3 = liveness failure), genuine = 0,
   attack = 1. Scored with leave-one-speaker-out cross-validation, so no call is scored by a
   model that heard its speaker; the weights written are then refitted on every call.
3. The AMBER cut-off on the fused risk r, chosen on the out-of-fold scores so that at most 5%
   of genuine calls from the registered number reach AMBER (every simulated call logs a
   high-risk request, so these are the deck's "genuine high-risk calls"). RED stays at the
   deck value unless AMBER has to sit close to it.
"""

from __future__ import annotations

import argparse
import json
import math

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

from engine.config import settings
from engine.fusion import FusionWeights, features
from ml.eval.report import cli_of

EVAL = settings.models_dir / "eval"
DRIFT_PERCENTILE = 99.0


def call_features(r: dict, w: FusionWeights) -> list[float] | None:
    """Rebuild the engine's fusion features from a simulated call's result."""
    f = r.get("features")
    if not f or f.get("s1") is None:
        return None
    # the engine reports the call-level S1 score, which is all x1 needs
    return list(features([f["s1"]], f.get("drift"), r.get("liveness"), w))


def fit_drift_threshold(rows: list[dict], default: float) -> tuple[float, int]:
    """99th percentile of S2 drift on genuine calls, and how many calls it came from (0 = default kept)."""
    d = [r["features"]["drift"] for r in rows if r["plan"]["level"] == "genuine" and (r.get("features") or {}).get("drift") is not None]
    return (float(np.percentile(d, DRIFT_PERCENTILE)), len(d)) if d else (default, 0)


def loso_splits(groups: list[str]) -> list[tuple[str, np.ndarray, np.ndarray]]:
    """Leave-one-speaker-out: (held-out speaker, train indices, test indices) per speaker."""
    g = np.asarray(groups)
    return [(s, np.flatnonzero(g != s), np.flatnonzero(g == s)) for s in sorted(set(groups))]


def fit_weights(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    """[w1, w2, w3, b]. Weights are kept non-negative (w1 >= 0.1) so no signal can lower the risk."""
    clf = LogisticRegression(C=1.0, class_weight="balanced").fit(X, y)
    w1, w2, w3 = (float(v) for v in clf.coef_[0])
    return np.array([max(w1, 0.1), max(w2, 0.0), max(w3, 0.0), float(clf.intercept_[0])])


def risk(X: np.ndarray, w: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-(X @ w[:3] + w[3])))


def pick_amber(scores: np.ndarray, max_rate: float, floor: float = 0.1, ceiling: float = 0.9) -> float:
    """Lowest sensible cut-off with at most `max_rate` of `scores` (genuine registered-number r) at or above it.
    Sits halfway between the last score allowed above it and the first that must stay below."""
    s = np.sort(np.asarray(scores, dtype=np.float64))[::-1]
    if not len(s):
        return settings.amber_at
    k = math.floor(max_rate * len(s) + 1e-9)  # how many genuine calls may reach AMBER
    if k >= len(s):
        return floor
    lower = float(s[k])
    upper = float(s[k - 1]) if k > 0 else min(1.0, lower + 0.1)
    cut = (lower + upper) / 2 if upper > lower else float(np.nextafter(lower, 2.0))
    return float(min(max(cut, floor), ceiling))


def _auc(y: np.ndarray, r: np.ndarray) -> float | None:
    return float(roc_auc_score(y, r)) if len(set(y.tolist())) == 2 else None


def _rates(r: np.ndarray, y: np.ndarray, reg: np.ndarray, amber: float, red: float) -> dict:
    g = r[(y == 0) & reg]
    a = r[y == 1]
    return {
        "genuine_registered": int(len(g)),
        "genuine_registered_amber_or_red": float(np.mean(g >= amber)) if len(g) else None,
        "attacks": int(len(a)),
        "attack_amber_or_red": float(np.mean(a >= amber)) if len(a) else None,
        "attack_red": float(np.mean(a >= red)) if len(a) else None,
        "auc": _auc(y, r),
    }


def fit(rows: list[dict], max_genuine_amber: float = 0.05, min_amber: float = 0.1, run: str = "dev") -> dict:
    base = FusionWeights()
    drift_threshold, n_drift = fit_drift_threshold(rows, base.drift_threshold)
    w0 = FusionWeights(drift_threshold=drift_threshold, drift_scale=base.drift_scale)
    X, y, spk, reg = [], [], [], []
    for r in rows:
        f = call_features(r, w0)
        if f is not None:
            X.append(f)
            y.append(0 if r["plan"]["level"] == "genuine" else 1)
            spk.append(r["plan"]["speaker"])
            reg.append(cli_of(r) == "registered")
    X, y, reg = np.array(X, dtype=np.float64).reshape(-1, 3), np.array(y), np.array(reg, dtype=bool)
    if len(set(y.tolist())) < 2:
        raise SystemExit("need both genuine and attack calls in the dev run")

    # leave-one-speaker-out: every call scored by weights fitted without its speaker
    oof = np.full(len(y), np.nan)
    fold_w: dict[str, np.ndarray | None] = {}
    for s, tr, te in loso_splits(spk):
        if len(set(y[tr].tolist())) < 2:
            fold_w[s] = None  # e.g. the only cloned speaker held out: nothing to learn attacks from
            continue
        fold_w[s] = fit_weights(X[tr], y[tr])
        oof[te] = risk(X[te], fold_w[s])
    scored = ~np.isnan(oof)
    amber = pick_amber(oof[scored & (y == 0) & reg], max_genuine_amber, floor=min_amber)
    red = min(0.95, max(settings.red_at, amber + 0.05))

    folds = []
    for s, _, te in loso_splits(spk):
        w = fold_w[s]
        row = {"speaker": s, "genuine": int(np.sum(y[te] == 0)), "attacks": int(np.sum(y[te] == 1)), "trained": w is not None}
        if w is not None:
            row["weights"] = dict(zip(["w1", "w2", "w3", "b"], (round(float(v), 4) for v in w), strict=True))
            row.update(_rates(oof[te], y[te], reg[te], amber, red))
        folds.append(row)

    w = fit_weights(X, y)
    return {
        "w1": float(w[0]),
        "w2": float(w[1]),
        "w3": float(w[2]),
        "b": float(w[3]),
        "drift_threshold": drift_threshold,
        "drift_scale": base.drift_scale,
        "amber_at": amber,
        "red_at": red,
        "source": f"fitted on IndiaCall run '{run}' ({len(y)} calls, {len(set(spk))} speakers, leave-one-speaker-out)",
        "drift_fit": {"percentile": DRIFT_PERCENTILE, "genuine_calls": n_drift, "kept_default": n_drift == 0},
        "amber_fit": {"max_genuine_registered": max_genuine_amber, "chosen_on": "out-of-fold scores", "floor": min_amber},
        "cv": {"pooled": {**_rates(oof[scored], y[scored], reg[scored], amber, red), "unscored_calls": int(np.sum(~scored))}, "folds": folds},
        "in_sample": _rates(risk(X, w), y, reg, amber, red),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev", default="dev")
    ap.add_argument("--max-genuine-amber", type=float, default=0.05, help="share of genuine registered-number calls allowed to reach AMBER")
    ap.add_argument("--min-amber", type=float, default=0.1, help="never set the AMBER cut-off below this")
    a = ap.parse_args()
    rows = [r for r in json.loads((EVAL / f"indiacall_{a.dev}.json").read_text())["results"] if not r.get("error")]
    out = fit(rows, a.max_genuine_amber, a.min_amber, run=a.dev)
    (settings.models_dir / "fusion.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
