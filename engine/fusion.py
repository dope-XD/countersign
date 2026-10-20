"""Signals -> voice risk r -> tier, with plain reason codes.

r = sigmoid(w1*x1 + w2*x2 + w3*x3 + b)
  x1 = logit of the S1 call score (mean of the top 3 windows in the last 20 s)
  x2 = how far S2 drift exceeds its genuine-call threshold (0 if below)
  x3 = liveness failure (0 = passed or not run, up to 1 = failed on lag, words and S1)
Weights, the drift threshold and the AMBER/RED cut-offs on r come from models/fusion.json
once fitted on IndiaCall dev calls (ml/eval/fit_fusion.py); the defaults below are hand-set
so the pipeline behaves sensibly before that. COUNTERSIGN_AMBER_AT / COUNTERSIGN_RED_AT, when
set, override the fitted cut-offs.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field

from engine.config import settings

TIERS = ["GREEN", "AMBER", "RED"]

REASON_TEXT = {
    "SYN_ARTIFACT_HIGH": "synthetic speech in {k} of {n} windows",
    "SYN_ARTIFACT_MED": "some synthetic-speech artefacts ({k} of {n} windows)",
    "SPK_DRIFT": "voice changed character mid-call",
    "RESP_LAG": "{lag:.1f} s to start repeating a short phrase",
    "NO_REPLY": "no reply to the challenge",
    "CHALLENGE_MISMATCH": "reply did not match the challenge words",
    "REPLAY_MATCH": "audio matches a confirmed fraud recording",
    "CLI_MISMATCH": "calling from an unregistered number",
    "SIM_SWAP_RECENT": "SIM swapped on the registered number in the last 72 h",
    "FRI_HIGH": "calling number rated {fri} on DoT FRI",
    "REPEAT_CALLS": "3 or more calls on this account today",
}


@dataclass
class FusionWeights:
    w1: float = 1.0
    w2: float = 2.5
    w3: float = 3.0
    b: float = 0.0
    drift_threshold: float = 0.45  # refit by ml/eval/fit_fusion.py on genuine IndiaCall calls
    drift_scale: float = 0.15
    amber_at: float = settings.amber_at  # cut-offs on r; fitted so <=5% of genuine registered-number calls reach AMBER
    red_at: float = settings.red_at
    source: str = "default"

    @classmethod
    def load(cls) -> FusionWeights:
        p = settings.models_dir / "fusion.json"
        if p.exists():
            d = json.loads(p.read_text())
            # an explicit environment override beats the fitted cut-off
            skip = {k for k in ("amber_at", "red_at") if f"COUNTERSIGN_{k.upper()}" in os.environ}
            return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d and k not in skip})
        return cls()


weights = FusionWeights.load()


def _logit(p: float) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


@dataclass
class Verdict:
    r: float
    voice_tier: str
    tier: str
    reasons: list[str]
    reason_text: list[str]
    features: dict = field(default_factory=dict)
    context_raised: bool = False


def call_s1_score(window_probs: list[float]) -> float:
    top = sorted(window_probs, reverse=True)[:3]
    return sum(top) / len(top) if top else 0.0


def features(window_probs: list[float], drift: float | None, liveness: dict | None, w: FusionWeights | None = None) -> tuple[float, float, float]:
    """(x1, x2, x3) as described at the top of this module. Shared with ml/eval/fit_fusion.py."""
    w = w or weights
    # no scored window yet: S1 gives no evidence either way (logit 0), rather than "certainly real"
    x1 = _logit(call_s1_score(window_probs)) if window_probs else 0.0
    x2 = min(2.0, max(0.0, (drift - w.drift_threshold) / w.drift_scale)) if drift is not None else 0.0
    fails = (liveness or {}).get("reasons", [])
    x3 = min(1.0, 0.5 * ("RESP_LAG" in fails or "NO_REPLY" in fails) + 0.5 * ("CHALLENGE_MISMATCH" in fails) + 0.5 * ("SYN_ARTIFACT_HIGH" in fails))
    return x1, x2, x3


def fuse(
    window_probs: list[float],
    drift: float | None,
    liveness: dict | None,
    context_flags: list[str],
    context_info: dict | None = None,
    replay_match: bool = False,
) -> Verdict:
    w = weights
    s1 = call_s1_score(window_probs)
    x1, x2, x3 = features(window_probs, drift, liveness, w)
    z = w.w1 * x1 + w.w2 * x2 + w.w3 * x3 + w.b
    r = 1 / (1 + math.exp(-z))

    voice_idx = 2 if r >= w.red_at else 1 if r >= w.amber_at else 0
    if replay_match:
        voice_idx = 2
    idx = voice_idx
    raised = False
    if context_flags and idx < 2:
        idx += 1
        raised = True

    # reasons: largest contributions first, then context flags. The SYN_* codes grade the S1
    # window probabilities against the deck cut-offs, not the fitted cut-offs on r.
    n = len(window_probs)
    k_hi = sum(p >= settings.red_at for p in window_probs[-10:])
    k_mid = sum(p >= settings.amber_at for p in window_probs[-10:])
    contrib: list[tuple[float, str]] = []
    if replay_match:
        contrib.append((99.0, "REPLAY_MATCH"))
    if s1 >= settings.red_at:
        contrib.append((w.w1 * x1, "SYN_ARTIFACT_HIGH"))
    elif s1 >= settings.amber_at:
        contrib.append((w.w1 * x1, "SYN_ARTIFACT_MED"))
    if x2 > 0:
        contrib.append((w.w2 * x2, "SPK_DRIFT"))
    if liveness:
        for code in liveness.get("reasons", []):
            if code != "SYN_ARTIFACT_HIGH" or s1 < settings.red_at:
                contrib.append((w.w3 * x3, code))
    codes = [c for _, c in sorted(contrib, key=lambda t: -t[0])]
    codes = list(dict.fromkeys(codes + list(context_flags)))[:3]

    info = context_info or {}
    lag = (liveness or {}).get("lag_s") or 0.0
    texts = [REASON_TEXT.get(c, c).format(k=k_hi if c == "SYN_ARTIFACT_HIGH" else k_mid, n=min(n, 10), lag=lag, fri=info.get("fri") or "high") for c in codes]
    return Verdict(
        r=r,
        voice_tier=TIERS[voice_idx],
        tier=TIERS[idx],
        reasons=codes,
        reason_text=texts,
        features={"s1": s1, "drift": drift, "x1": x1, "x2": x2, "x3": x3, "windows": n},
        context_raised=raised,
    )
