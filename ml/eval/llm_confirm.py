"""The smarter check offline: Gemma 4 E2B (the phone's model family) on a laptop through Ollama, with the phone's exact
prompt (assets/llm_prompt.txt) and parser (engine/listener/llm.py).

    ollama pull gemma4:e2b-it-q4_K_M
    python -m ml.eval.llm_confirm                  # → models/eval/llm_confirm.json + llm_verdicts.json (for hybrid_eval --llm)
    python -m ml.eval.llm_confirm --limit 40       # at most 40 calls per set (quick look)

Sets: our team calls and adversarial texts, near-domain genuine calls (a real bank, courier or police officer using
scam words; data/listener/near_domain.jsonl), and samples of the Hinglish and BothBosu held-out calls. Each call is
judged once on its last ~1,500 characters with the signal `unknown_number`, which is what the phone sends at warn.

Gates (docs/RESULTS.md): false `scam` on near-domain genuine calls at most 5%. If it fails, fusion.json `llm.can_raise`
goes to false and the smarter check only writes the reason on the card.
"""

from __future__ import annotations

import argparse
import json
import random
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

from engine.listener.llm import parse, prompt
from ml import listener_data
from ml.eval.hybrid_eval import near_domain

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "models" / "eval" / "llm_confirm.json"
VERDICTS = ROOT / "models" / "eval" / "llm_verdicts.json"
MODEL = "gemma4:e2b-it-q4_K_M"
URL = "http://localhost:11434/api/generate"
SAMPLED = ("hinglish_calls", "bothbosu")


def ask(text: str, model: str) -> tuple[str, float]:
    body = json.dumps({"model": model, "prompt": text, "stream": False, "think": False, "options": {"temperature": 0, "num_predict": 200}}).encode()
    t = time.perf_counter()
    with urllib.request.urlopen(urllib.request.Request(URL, body, {"Content-Type": "application/json"}), timeout=600) as r:
        out = json.loads(r.read())["response"]
    return out, time.perf_counter() - t


def rows(limit: int | None) -> list[dict]:
    all_rows = [r for r in listener_data.load() if r["split"].startswith("test")]
    out = [r for r in all_rows if r["source"] in ("team_calls", "adversarial")] + near_domain()
    rng = random.Random(7)
    for src in SAMPLED:
        pool = [r for r in all_rows if r["source"] == src]
        for label in (0, 1):
            group = [r for r in pool if r["label"] == label]
            out += rng.sample(group, min(len(group), (limit or 60) // 2))
    if limit:
        by = defaultdict(list)
        for r in out:
            by[r["source"]].append(r)
        out = [r for v in by.values() for r in v[:limit]]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--model", default=MODEL)
    a = ap.parse_args()
    done = json.loads(VERDICTS.read_text(encoding="utf-8")) if VERDICTS.exists() else {}
    calls, stats = [], defaultdict(lambda: defaultdict(int))
    for r in rows(a.limit):
        if r["id"] in done and "seconds" in done[r["id"]]:
            v, secs, raw = done[r["id"]], done[r["id"]]["seconds"], None
        else:
            raw, secs = ask(prompt(r["text"], {"unknown_number"}), a.model)
            p = parse(raw)
            v = {"verdict": p.verdict, "type": p.type, "reason_en": p.reason_en, "reason_hi": p.reason_hi} if p else {"verdict": "unparsed"}
            done[r["id"]] = {**v, "seconds": round(secs, 2)}
            VERDICTS.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
        s = stats[r["source"]]
        s["n_scam" if r["label"] else "n_genuine"] += 1
        s[f"{v['verdict']}_{'scam' if r['label'] else 'genuine'}"] += 1
        calls.append({"id": r["id"], "label": r["label"], "verdict": v["verdict"], "seconds": secs, "raw": raw})

    def pct(x: int, n: int) -> str:
        return f"{100 * x / n:.1f}%" if n else "-"

    table = [
        "| set | scam calls | said scam | said unsure | genuine calls | false scam | said ok on genuine | unparsed |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for src, s in sorted(stats.items()):
        unparsed = s["unparsed_scam"] + s["unparsed_genuine"]
        table.append(
            f"| {src} | {s['n_scam']} | {pct(s['scam_scam'], s['n_scam'])} | {pct(s['unsure_scam'], s['n_scam'])} | {s['n_genuine']} | "
            f"{pct(s['scam_genuine'], s['n_genuine'])} | {pct(s['ok_genuine'], s['n_genuine'])} | {unparsed} |"
        )
    secs = sorted(c["seconds"] for c in calls)
    near = stats["near_domain"]
    gate = near["n_genuine"] and near["scam_genuine"] / near["n_genuine"] <= 0.05
    summary = {
        "model": a.model,
        "median_seconds_laptop": secs[len(secs) // 2] if secs else None,
        "gate_near_domain_false_scam_le_5pct": bool(gate),
        "sets": {k: dict(v) for k, v in stats.items()},
    }
    OUT.write_text(json.dumps({**summary, "markdown": "\n".join(table), "calls": calls}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(table))
    print(json.dumps({k: v for k, v in summary.items() if k != "sets"}))


if __name__ == "__main__":
    main()
