"""The two judges together (port of record for data/listen/Hybrid.kt), CONTRACT.md "Call listener".

    conversation check (conversation.py, with the model pack) ─┐
    cue rules + fusion (rules.py, fusion.py; basic mode adds   ├─► combine() ─► none / watch / warn / scam
      our small classifier)                                    │
    the smarter check (llm.py, optional), the user, the server ┘

- watch / warn: the higher of the two judges.
- scam needs two independent sources: a judge at scam from what was said alone plus another source at warn or above
  (the other judge, the smarter check), or a judge that already paired what was said with what the phone saw (a strong
  context signal, or the classifier with the cue words), or the call at warn plus the smarter check saying scam.
  Without the model pack (basic mode) the cue rules' own scam stands, as before.
- The phone's own signals derived from the words: `digits_read_out` (the owner read 4-8 digits on an unknown call) and
  `bank_claim_not_1600` (a bank or authority claim on an unknown number that isn't 1600-series).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from engine.listener.conversation import Call as ConvCall
from engine.listener.conversation import config as conv_config
from engine.listener.conversation import conv_model, text_segments, window
from engine.listener.fusion import LEVELS, Verdict, config, fuse, higher
from engine.listener.llm import LlmVerdict
from engine.listener.rules import ASSETS, CallScorer, digits_read_out, normalize

BANK_CLAIM = {"authority", "verification_pretext"}
TRUSTED = {"known_contact", "caller_verified"}
PHONE = {"context", "caller_check", "voice"}


def at_least(level: str, floor: str) -> bool:
    return LEVELS.index(level) >= LEVELS.index(floor)


def derived(context: set[str], tokens: list[str], said: set[str]) -> set[str]:
    """Signals the phone derives from the words: [said] is the cue categories and the conversation's moves so far."""
    out = set(context)
    unknown = "unknown_number" in out or ("video_call_unknown" in out and not out & TRUSTED)
    if unknown and digits_read_out(tokens):
        out.add("digits_read_out")
    if "unknown_number" in out and "series_1600" not in out and said & BANK_CLAIM:
        out.add("bank_claim_not_1600")
    return out


def combine(
    cue: Verdict,
    conv: Verdict | None = None,
    conv_model: str = "none",
    llm: LlmVerdict | None = None,
    server: Verdict | None = None,
    user: bool = False,
    prev: str = "none",
    llm_can_raise: bool = True,
) -> tuple[Verdict, LlmVerdict | None]:
    """[cue]: fuse() without server, user or prev. [conv]: the conversation check's verdict, [conv_model] its model's
    own level (what was said only). Returns the verdict and the smarter check's verdict whose reason the card shows."""

    def cap(x: str) -> str:
        return "warn" if x == "scam" else x

    level = cap(cue.level)
    if conv is not None:
        # cue words alone are not enough for amber while the conversation model hears nothing of a scam (genuine bank
        # and courier calls use the same words); a phone signal still is
        if level == "warn" and conv_model == "none" and not set(cue.sources) & PHONE:
            level = "watch"
        level = higher(level, cap(conv.level))
    llm_scam = llm is not None and llm.verdict == "scam"
    raise_llm = llm_scam and llm_can_raise
    if conv is None:
        red = cue.level == "scam"  # basic mode: the cue rules' own scam, as before
    else:
        conv_said = conv_model == "scam"
        conv_paired = conv.level == "scam" and not conv_said  # the conversation at warn + a strong phone signal
        cue_paired = cue.level == "scam" and not cue.alone
        red = (
            conv_paired
            or cue_paired
            or (conv_said and (at_least(cue.level, "warn") or raise_llm))
            or (cue.level == "scam" and cue.alone and (at_least(conv_model, "warn") or raise_llm))
        )
    red = red or (raise_llm and at_least(level, "warn"))
    if red:
        level = "scam"

    sources = set(cue.sources) | (set(conv.sources) if conv is not None else set())
    if llm_scam and at_least(level, "warn"):
        sources.add("llm")
    kind = conv.type if conv is not None and conv.type != "unknown" else cue.type
    if kind == "unknown" and llm_scam and llm.type != "unknown":
        kind = llm.type
    cues = list(conv.cues) if conv is not None else []
    cues += [c for c in cue.cues if c not in cues]

    if server is not None and server.level != "none":
        level = higher(level, server.level)
        if kind == "unknown":
            kind = server.type
        sources.add("server")
        cues += [c for c in server.cues if c != "discussion" and c not in cues]
    if user:
        level = "scam"
        sources.add("user")
    level = higher(level, prev)
    shown = llm if llm_scam and at_least(level, "warn") else None
    return Verdict(level, kind, cues, sorted(sources)), shown


@dataclass
class HybridCall:
    """One live call (the twin of Analyzer.Call on the phone with the model pack): both judges, then combine()."""

    p_of: object = None
    embed: object = None
    conv: ConvCall = None  # type: ignore[assignment]
    scorer: CallScorer = field(default_factory=CallScorer)
    tokens: list[str] = field(default_factory=list)
    context: set[str] = field(default_factory=set)
    llm: LlmVerdict | None = None
    user: bool = False
    server: Verdict | None = None
    prev: str = "none"
    verdict: Verdict = field(default_factory=lambda: Verdict("none", "unknown", [], []))
    shown: LlmVerdict | None = None

    def __post_init__(self):
        if self.conv is None:
            self.conv = ConvCall(p_of=self.p_of, embed=self.embed)

    def feed(self, segment: str) -> Verdict:
        if segment.strip():
            self.conv.feed(segment)
            self.scorer.feed(segment)
            self.tokens += normalize(segment)
        return self.update()

    def set_context(self, context: set[str]) -> Verdict:
        self.context = set(context)
        return self.update()

    def set_llm(self, v: LlmVerdict | None) -> Verdict:
        self.llm = v
        return self.update()

    def update(self) -> Verdict:
        cues = self.scorer.result()
        ctx = derived(self.context, self.tokens, set(cues.categories) | set(self.conv.reasons))
        st = self.conv.set_context(ctx)
        conv = Verdict(st.level, st.type, st.reasons, st.sources)
        cue = fuse(cues, ctx)
        self.verdict, self.shown = combine(
            cue, conv, self.conv.acc.model_level, self.llm, self.server, self.user, self.prev, config().get("llm", {}).get("can_raise", True)
        )
        self.prev = self.verdict.level
        return self.verdict


def analyze_text(text: str, context: set[str] | frozenset[str] = frozenset(), llm: LlmVerdict | None = None, **kw) -> Verdict:
    """ "Check a recording or message" with the model pack (Analyzer.text): the segments as a call, then the whole
    text once more through the conversation model (a whole message is all the evidence there will be)."""
    c = HybridCall(**kw)
    c.set_context(set(context))
    segs = text_segments(text)
    for s in segs:
        c.feed(s)
    if llm is not None:
        c.set_llm(llm)
    p_of = kw.get("p_of") or conv_model().run
    whole = float(p_of(window(segs))) if segs else 0.0
    v = c.verdict
    if whole >= conv_config()["t_scam"] and v.level == "warn":
        v = Verdict("scam", v.type, v.cues, v.sources)
    return v


def write_vectors() -> None:
    """Shared vectors for HybridTest.kt: the conversation vectors' recorded model outputs, replayed through both
    judges with context and smarter-check verdicts, so the phone's combiner is checked without running any model."""
    path = ASSETS.parents[1] / "test" / "resources" / "conv_vectors.json"
    calls = json.loads(path.read_text(encoding="utf-8"))["calls"]
    llms = [
        None,
        LlmVerdict("scam", "digital_arrest", "They threaten arrest and ask for money.", "वे गिरफ़्तारी की धमकी देकर पैसे मांग रहे हैं।"),
        LlmVerdict("ok"),
        LlmVerdict("unsure"),
    ]
    ctxs = [
        [],
        ["unknown_number"],
        ["unknown_number", "international_number"],
        ["unknown_number", "series_1600"],
        ["video_call_unknown"],
        ["unknown_number", "remote_app_opened"],
    ]
    # (never a trusted signal here: it changes the conversation's thresholds, so the recorded model outputs wouldn't cover the call)
    out = []
    for i, c in enumerate(calls):
        p, emb = c["p"], c["emb"]
        ctx = sorted(set(c["context"]) | set(ctxs[i % len(ctxs)]))
        llm = llms[(i // 2) % len(llms)]
        h = HybridCall(p_of=lambda w, p=p: p[w], embed=lambda t, emb=emb: emb[t])
        h.set_context(set(ctx))
        levels = []
        for k, s in enumerate(c["segments"]):
            h.feed(s)
            if llm is not None and k == len(c["segments"]) // 2:
                h.set_llm(llm)
            levels.append(h.verdict.level)
        out.append(
            {
                "id": c["id"],
                "segments": c["segments"],
                "context": ctx,
                "llm": None if llm is None else llm.__dict__,
                "levels": levels,
                "level": h.verdict.level,
                "type": h.verdict.type,
                "cues": h.verdict.cues,
                "sources": h.verdict.sources,
                "reason": None if h.shown is None else h.shown.reason_en,
            }
        )
    dst = ASSETS.parents[1] / "test" / "resources" / "hybrid_vectors.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(out)} hybrid vectors to {dst}")


if __name__ == "__main__":
    write_vectors()
