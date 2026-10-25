"""A transcript or message → the phone's verdict: cues, our classifier, context and the voice score, through fusion.

Port of record for data/listen/Analyzer.kt (`Analyzer.text`), used by ml.eval.kit and ml.eval.run_all so the
laptop reproduces exactly what the phone shows on "Check a recording or message".
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.listener.classifier import Classifier, classifier
from engine.listener.fusion import Judge, fuse
from engine.listener.hybrid import derived
from engine.listener.rules import CallScorer, normalize, score_text

SYNTHETIC_VOICE = "synthetic_voice"
EVIDENCE = {"remote_app_opened", "caller_check_failed", "video_call_unknown", "international_number", "long_call"}


@dataclass
class Analysis:
    level: str
    type: str
    p_scam: float | None
    cues: list[str]
    sources: list[str]
    voice_clone: float | None = None
    transcript: str = ""
    seconds: float = 0.0


def signals(context: set[str], voice: float | None, threshold: float) -> set[str]:
    return set(context) | ({SYNTHETIC_VOICE} if voice is not None and voice >= threshold else set())


def analyze_text(
    text: str,
    context: set[str] | frozenset[str] = frozenset(),
    voice_clone: float | None = None,
    seconds: float = 0.0,
    min_words: int | None = None,
    clf: Classifier | None = None,
    voice_threshold: float = 0.5,
    cfg: dict | None = None,
) -> Analysis:
    clf = clf or classifier()
    j = clf.judge(text, min_words=clf.meta["min_words_text"] if min_words is None else min_words)
    cues = score_text(text)
    ctx = derived(signals(set(context), voice_clone, voice_threshold), normalize(text), set(cues.categories))
    v = fuse(cues, ctx, judge=j, cfg=cfg)
    why = list(dict.fromkeys(v.cues + sorted(c for c in ctx if c == SYNTHETIC_VOICE or c in EVIDENCE)))
    return Analysis(
        level=v.level,
        type="unknown" if v.level == "none" else v.type,
        p_scam=None if j.abstain else j.p_scam,
        cues=why,
        sources=[s for s in v.sources if s != "user"],
        voice_clone=voice_clone,
        transcript=text,
        seconds=seconds,
    )


@dataclass
class LiveCall:
    """The live-call twin of Analyzer.Call: feed recognised segments one by one; levels never go down."""

    clf: Classifier = field(default_factory=classifier)
    scorer: CallScorer = field(default_factory=CallScorer)
    words: list[str] = field(default_factory=list)
    tokens: list[str] = field(default_factory=list)
    context: set[str] = field(default_factory=set)
    prev: str = "none"

    def feed(self, text: str) -> str:
        if text.strip():
            self.scorer.feed(text)
            self.words.append(text)
            self.tokens += normalize(text)
        j: Judge = self.clf.judge(" ".join(self.words), min_words=self.clf.meta["min_words_call"])
        cues = self.scorer.result()
        ctx = derived(self.context, self.tokens, set(cues.categories))
        self.prev = fuse(cues, ctx, judge=j, prev=self.prev).level
        return self.prev


def write_vectors() -> None:
    """Shared vectors for AnalyzerTest: the held-out team and adversarial texts, with and without context."""
    import json

    from engine.listener.rules import ASSETS
    from ml import listener_data

    rows = [r for r in listener_data.load() if r["source"] in ("adversarial", "team_calls")]
    out = []
    for i, r in enumerate(rows):
        ctx = [["remote_app_opened"], ["caller_check_failed"], []][i % 3] if i % 4 == 0 else []
        voice = [None, 0.2, 0.9][i % 3]
        a = analyze_text(r["text"], set(ctx), voice_clone=voice)
        out.append(
            {
                "id": r["id"],
                "text": r["text"],
                "context": ctx,
                "voice": voice,
                "level": a.level,
                "type": a.type,
                "cues": a.cues,
                "sources": a.sources,
                "p_scam": a.p_scam,
            }
        )
    path = ASSETS.parents[1] / "test" / "resources" / "analyzer_vectors.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(out)} vectors to {path}")


if __name__ == "__main__":
    write_vectors()
