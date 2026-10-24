"""Fusion: cues, our scam classifier, context signals and the voice check → one level (fusion.json).

Port of record for data/listen/Fusion.kt. Levels never go down during a call.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from engine.listener.rules import ASSETS, Result, rules

LEVELS = ["none", "watch", "warn", "scam"]


@cache
def config(path: Path = ASSETS / "fusion.json") -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Judge:
    """What the scam classifier (ml/listener_clf.py) said about the transcript so far."""

    p_scam: float
    type: str = "unknown"
    abstain: bool = False


@dataclass(frozen=True)
class Verdict:
    level: str
    type: str
    cues: list[str]
    sources: list[str]


def higher(a: str, b: str) -> str:
    return a if LEVELS.index(a) >= LEVELS.index(b) else b


def fuse(
    cues: Result,
    context: set[str] | frozenset[str] = frozenset(),
    judge: Judge | None = None,
    user: bool = False,
    prev: str = "none",
) -> Verdict:
    f, r = config(), rules()
    cats = (set(cues.categories) - {"discussion"}) | (set(context) & set(f["context_as_category"]))
    strong = cats - r.weak
    extra = f["trusted_extra"] if set(context) & set(f["trusted_context"]) else 0
    j = judge if judge and not judge.abstain else None
    sources: set[str] = set()
    level = "none"

    if len(cats) >= f["watch"]["min_categories"]:
        level = "watch"
        sources.add("cues")

    w = f["warn"]
    vetoed = bool(j and j.p_scam < w["clf_veto_below"])  # the classifier is sure it's harmless
    warn_cues = len(strong) >= w["min_strong"] + extra and not vetoed
    warn_clf = bool(j and j.p_scam >= w["clf_p"] and len(cats) >= w["clf_min_categories"])
    warn_ctx = set(context) & set(w["context_alone"])
    if warn_cues or warn_clf or warn_ctx:
        level = "warn"
        if warn_clf:
            sources.add("phone_ai")
        if "caller_check_failed" in warn_ctx:
            sources.add("caller_check")
        if "synthetic_voice" in warn_ctx:
            sources.add("voice")
        if warn_ctx - {"caller_check_failed", "synthetic_voice"}:
            sources.add("context")

    s = f["scam"]
    scam_cues = (
        len(cats) >= s["cues_min_categories"] + extra
        and (not s["cues_need_action"] or bool(cats & r.action))
        and (not s["cues_need_type"] or cues.type != "unknown")
        and not (s["discussion_blocks_cues"] and cues.discussion)
    )
    scam_clf = (
        bool(j and j.p_scam >= s["clf_p"] and len(cats) >= s["clf_min_categories"])
        and (not s["clf_needs_cue_warn"] or warn_cues)
        and not (s["discussion_blocks_cues"] and cues.discussion)
    )
    strong_ctx = set(context) & set(s["strong_context"])
    # two independent kinds of evidence: what was said (cues or the classifier) and what the phone saw
    scam_ctx = bool(strong_ctx) and (warn_cues or warn_clf)
    if scam_cues or scam_clf or scam_ctx or user:
        level = "scam"
        if scam_ctx:
            sources.add("caller_check" if "caller_check_failed" in strong_ctx else "context")
        if scam_clf:
            sources.add("phone_ai")
        if user:
            sources.add("user")

    kind = cues.type
    if kind == "unknown" and j and j.type != "unknown":
        kind = j.type
    if kind == "unknown" and "caller_check_failed" in context:
        kind = "impersonation"

    level = higher(level, prev)
    return Verdict(level, kind, sorted(cats), sorted(sources))
