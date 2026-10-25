"""The two judges together (engine/listener/hybrid.py) against the conversation check alone and the cue rules alone, on the
held-out text sets: every call is fed segment by segment as the phone would, on an unknown number.

    python -m ml.eval.hybrid_eval            # → models/eval/hybrid.json (+ a markdown table on stdout)
    python -m ml.eval.hybrid_eval --llm      # also the smarter check's verdicts from ml.eval.llm_confirm (llm_verdicts.json)

Per set and path: recall at warn and at scam (scam calls), false warn and false scam (genuine calls). Model outputs
are cached per window (data/conv/p_cache.json) so reruns are quick.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from engine.listener.conversation import Call as ConvCall
from engine.listener.conversation import base_model, conv_model, text_segments
from engine.listener.fusion import LEVELS, fuse
from engine.listener.hybrid import HybridCall, derived
from engine.listener.llm import LlmVerdict
from engine.listener.rules import CallScorer, normalize
from ml import listener_data

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "conv" / "p_cache.json"
OUT = ROOT / "models" / "eval" / "hybrid.json"
SETS = ("team_calls", "adversarial", "hinglish_calls", "bothbosu")
CONTEXT = {"unknown_number"}
NEAR = ROOT / "data" / "listener" / "near_domain.jsonl"


class Cached:
    def __init__(self):
        self.p = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
        self.e: dict[str, list[float]] = {}
        self.new = 0

    def p_of(self, w: str) -> float:
        if w not in self.p:
            self.p[w] = float(conv_model().run(w))
            self.new += 1
        return self.p[w]

    def embed(self, t: str):
        if t not in self.e:
            self.e[t] = base_model().run(t, 64)
        return self.e[t]

    def save(self) -> None:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(self.p), encoding="utf-8")


def near_domain() -> list[dict]:
    """Genuine calls that sound like scams (a real bank, courier, police; data/listener/near_domain.jsonl)."""
    out = []
    for line in NEAR.read_text(encoding="utf-8").splitlines():
        if line.strip():
            a = json.loads(line)
            out.append({"id": f"near_domain/{a['id']}", "text": a["text"], "label": a["label"], "source": "near_domain", "lang": a["lang"], "split": "test"})
    return out


def segments(row: dict, team: dict) -> list[str]:
    if row["source"] == "team_calls":
        return team[row["id"].split("/", 1)[1]]
    return text_segments(row["text"])


def run(segs: list[str], m: Cached, llm: LlmVerdict | None) -> dict[str, str]:
    conv = ConvCall(p_of=m.p_of, embed=m.embed)
    conv.set_context(CONTEXT)
    scorer, tokens, prev = CallScorer(), [], "none"
    h = HybridCall(p_of=m.p_of, embed=m.embed)
    h.set_context(CONTEXT)
    for i, s in enumerate(segs):
        conv.feed(s)
        scorer.feed(s)
        tokens += normalize(s)
        cues = scorer.result()
        prev = fuse(cues, derived(CONTEXT, tokens, set(cues.categories)), prev=prev).level
        h.feed(s)
        if llm is not None and LEVELS.index(h.verdict.level) >= LEVELS.index("warn") and i >= 1:
            h.set_llm(llm)
    return {"conv_only": conv.state().level, "cues_only": prev, "hybrid": h.verdict.level}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true")
    a = ap.parse_args()
    llms = {}
    if a.llm:
        path = ROOT / "models" / "eval" / "llm_verdicts.json"
        llms = {k: LlmVerdict(**v) for k, v in json.loads(path.read_text(encoding="utf-8")).items()}
    team = {t["id"]: t["turns"] for t in json.loads(listener_data.TEAM.read_text(encoding="utf-8"))["transcripts"]}
    rows = [r for r in listener_data.load() if r["source"] in SETS and r["split"].startswith("test")]
    rows += near_domain()
    m = Cached()
    counts: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    per_call = []
    for r in rows:
        levels = run(segments(r, team), m, llms.get(r["id"]))
        if a.llm and r["id"] in llms:
            levels["hybrid_llm"] = levels.pop("hybrid")
        per_call.append({"id": r["id"], "label": r["label"], **levels})
        for path, lvl in levels.items():
            c = counts[(r["source"], path)]
            c["n_scam" if r["label"] else "n_genuine"] += 1
            if LEVELS.index(lvl) >= LEVELS.index("warn"):
                c["warn_scam" if r["label"] else "warn_genuine"] += 1
            if lvl == "scam":
                c["red_scam" if r["label"] else "red_genuine"] += 1
        if m.new >= 500:
            m.save()
            m.new = 0
    m.save()

    def pct(x: int, n: int) -> str:
        return f"{100 * x / n:.1f}%" if n else "-"

    table = [
        "| set | path | scam calls | recall at warn | recall at scam | genuine calls | false warn | false scam |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    summary = {}
    for (src, path), c in sorted(counts.items()):
        summary[f"{src}/{path}"] = dict(c)
        table.append(
            f"| {src} | {path} | {c['n_scam']} | {pct(c['warn_scam'], c['n_scam'])} | {pct(c['red_scam'], c['n_scam'])} | {c['n_genuine']} | "
            f"{pct(c['warn_genuine'], c['n_genuine'])} | {pct(c['red_genuine'], c['n_genuine'])} |"
        )
    OUT.write_text(json.dumps({"context": sorted(CONTEXT), "summary": summary, "calls": per_call, "markdown": "\n".join(table)}, indent=1), encoding="utf-8")
    print("\n".join(table))


if __name__ == "__main__":
    main()
