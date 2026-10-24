"""Fusion: cues, the LLM judge, context signals and the server's verdict → one level (fusion.json).

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
    """What an LLM judge said about the transcript so far."""

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
    server: Verdict | None = None,
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
    warn_cues = len(strong) >= w["min_strong"] + extra
    warn_llm = bool(j and j.p_scam >= w["llm_p"] and len(cats) >= w["llm_min_categories"])
    warn_ctx = set(context) & set(w["context_alone"])
    if warn_cues or warn_llm or warn_ctx:
        level = "warn"
        if warn_llm:
            sources.add("phone_ai")
        if warn_ctx:
            sources.add("caller_check" if "caller_check_failed" in warn_ctx else "context")

    s = f["scam"]
    scam_cues = (
        len(cats) >= s["cues_min_categories"] + extra
        and (not s["cues_need_action"] or bool(cats & r.action))
        and (not s["cues_need_type"] or cues.type != "unknown")
        and not (s["discussion_blocks_cues"] and cues.discussion)
    )
    scam_llm = bool(j and j.p_scam >= s["llm_p"] and len(cats) >= s["llm_min_categories"])
    strong_ctx = set(context) & set(s["strong_context"])
    # two independent kinds of evidence: what was said (cues or the judge) and what the phone saw
    scam_ctx = bool(strong_ctx) and (warn_cues or warn_llm)
    if scam_cues or scam_llm or scam_ctx or user:
        level = "scam"
        if scam_ctx:
            sources.add("caller_check" if "caller_check_failed" in strong_ctx else "context")
        if scam_llm:
            sources.add("phone_ai")
        if user:
            sources.add("user")

    kind = cues.type
    if kind == "unknown" and j and j.type != "unknown":
        kind = j.type
    if kind == "unknown" and "caller_check_failed" in context:
        kind = "impersonation"

    if server is not None:
        # the server heard the same call with a stronger model and the same context: it decides,
        # except that the user's own "Alert family" always stands
        level = higher(server.level, "scam" if user else "none")
        kind = server.type if server.type != "unknown" else kind
        sources |= set(server.sources) | {"server"}
    level = higher(level, prev)
    return Verdict(level, kind, sorted(cats), sorted(sources))
