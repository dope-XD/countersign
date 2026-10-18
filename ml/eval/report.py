"""Merge benchmark and IndiaCall results into models/metrics.json for the metrics page.

python -m ml.eval.report --indiacall test
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import Counter, defaultdict

import numpy as np

from engine.config import settings
from ml.eval.indiacall_sim import LEVELS
from ml.eval.metrics import wilson

EVAL = settings.models_dir / "eval"
LANG = {"en": "English", "hi": "Hindi", "hinglish": "Hinglish"}


def indiacall_section(run: str) -> dict | None:
    p = EVAL / f"indiacall_{run}.json"
    if not p.exists():
        return None
    rows = [r for r in json.loads(p.read_text())["results"] if not r.get("error")]
    errors = [r for r in json.loads(p.read_text())["results"] if r.get("error")]
    gen = [r for r in rows if r["plan"]["level"] == "genuine"]
    att = [r for r in rows if r["plan"]["level"] != "genuine"]
    stepped = [r for r in gen if r["final_tier"] in ("AMBER", "RED")]
    approved = [r for r in att if r["executed"]]
    first = [r["first_tier_s"] for r in rows if r.get("first_tier_s") is not None]

    levels = []
    for lvl, desc in LEVELS.items():
        rs = [r for r in att if r["plan"]["level"] == lvl]
        levels.append(
            {
                "level": lvl,
                "description": desc,
                "calls": len(rs),
                "approved": sum(r["executed"] for r in rs),
                "tiers": dict(Counter(r["final_tier"] or "none" for r in rs)),
            }
        )

    overall = len(stepped) / len(gen) if gen else 0.0
    fairness = []
    for lang in sorted({r["language"] for r in gen}):
        g = [r for r in gen if r["language"] == lang]
        k = sum(r["final_tier"] in ("AMBER", "RED") for r in g)
        fairness.append({"group": LANG.get(lang, lang), "n": len(g), "fpr": k / len(g), "ci": list(wilson(k, len(g)))})
    by_spk = defaultdict(list)
    for r in gen:
        by_spk[r["plan"]["speaker"]].append(r)
    for spk, g in sorted(by_spk.items()):
        k = sum(r["final_tier"] in ("AMBER", "RED") for r in g)
        fairness.append({"group": f"Speaker {spk}", "n": len(g), "fpr": k / len(g), "ci": list(wilson(k, len(g)))})

    misses = []
    for r in att:
        if r["final_tier"] != "RED":
            misses.append(
                {
                    "id": r["plan"]["id"],
                    "level": r["plan"]["level"],
                    "language": LANG.get(r["language"], r["language"]),
                    "tier": r["final_tier"] or "none",
                    "why": f"generator {r['plan']['generator']}; S1 call score {((r.get('features') or {}).get('s1') or 0):.2f}; liveness {'passed' if (r.get('liveness') or {}).get('passed') else 'failed'}"
                    + ("; change was made" if r["executed"] else "; change still blocked by app approval"),
                }
            )
    for r in stepped:
        misses.append(
            {
                "id": r["plan"]["id"],
                "level": "genuine",
                "language": LANG.get(r["language"], r["language"]),
                "tier": r["final_tier"],
                "why": "genuine caller given an extra check: " + ", ".join(r.get("reasons") or []),
            }
        )

    p95_first = float(np.percentile(first, 95)) if first else None
    targets = [
        {
            "name": "Risky changes approved for attackers L1 to L4",
            "target": f"0 of {len(att)}",
            "result": f"{len(approved)} of {len(att)}",
            "pass": len(approved) == 0,
        },
        {
            "name": f"Genuine callers given an extra check ({len(gen)} genuine calls)",
            "target": "5% or fewer",
            "result": f"{len(stepped)} ({overall:.0%})",
            "pass": overall <= 0.05,
        },
        {
            "name": "Genuine callers who completed the change with app approval",
            "target": "all",
            "result": f"{sum(r['executed'] for r in gen)} of {len(gen)}",
            "pass": all(r["executed"] for r in gen) if gen else None,
        },
        {
            "name": "First tier on the agent's screen (p95)",
            "target": "within 8 s",
            "result": f"{p95_first:.1f} s" if p95_first else "—",
            "pass": (p95_first <= 8.0) if p95_first else None,
        },
        {"name": "Attack calls flagged RED", "target": "—", "result": f"{sum(r['final_tier'] == 'RED' for r in att)} of {len(att)}", "pass": None},
    ]
    worst = max((f["fpr"] for f in fairness if not f["group"].startswith("Speaker")), default=0)
    targets.append(
        {
            "name": "False alarms per language vs overall",
            "target": "under 2× overall",
            "result": f"worst {worst:.0%} vs {overall:.0%}",
            "pass": (worst <= 2 * overall) if overall > 0 else worst == 0,
        }
    )
    return {
        "targets": targets,
        "levels": levels,
        "genuine": {"calls": len(gen), "stepped_up": len(stepped), "rate": overall},
        "first_tier_s": {"p50": float(np.median(first)), "p95": p95_first} if first else None,
        "fairness": fairness,
        "misses": misses,
        "errors": len(errors),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--indiacall", default="test")
    a = ap.parse_args()
    benchmarks = []
    model = None
    for p in sorted(EVAL.glob("bench_*.json")):
        d = json.loads(p.read_text())
        model = d.get("model", model)
        benchmarks += d["results"]
    ic = indiacall_section(a.indiacall)
    fusion = settings.models_dir / "fusion.json"
    notes = [
        "Detector EERs use the first 4 s of each clip, passed through the named phone channel (ffmpeg codecs).",
        "IndiaCall: teammates' consented voices and their clones, streamed through the live engine over G.711. Reply delays are sampled from live-call measurements; audio, words, scoring, policy and passkey signatures are real.",
        "Speakers whose voices were cloned were never in S1 training data.",
    ]
    if ic and ic.get("errors"):
        notes.append(f"{ic['errors']} simulated calls failed to run and are excluded.")
    out = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "model": {"s1": model or "unknown", "fusion": json.loads(fusion.read_text()).get("source", "fitted") if fusion.exists() else "default weights"},
        "benchmarks": benchmarks,
        "indiacall": ic,
        "notes": notes,
    }
    (settings.models_dir / "metrics.json").write_text(json.dumps(out, indent=2))
    print("wrote models/metrics.json")


if __name__ == "__main__":
    main()
