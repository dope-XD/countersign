"""Set the call thresholds on dev, then measure the conversation check on every held-out set (old vs new).

    python -m ml.eval.conv_eval calibrate     # data/conv/dev.scored.parquet → android/app/src/main/assets/conv.json
    python -m ml.eval.conv_eval measure       # data/conv/test_*.scored.parquet → docs/results_conv.json (+ a table)
    python -m ml.eval.conv_eval basic         # the old path (basic mode) on the same ICFD calls → docs/results_basic_icfd.json

Each row of a scored file is one moment of a call (the call so far, its p from ml.conv_score). A call is replayed
moment by moment through the Accumulator exactly as the phone would (repeated moments with no new words are
skipped). Thresholds are chosen on dev calls only so that a fixed share of genuine calls ever reach each level:
watch 10%, warn 3%, scam 0.5% (the stricter thresholds for a trusted caller: 3%, 0.5%, 0.1%).

ICFD-31k's validation and test splits hold only scam calls; its genuine calls come from the 10% of its train
conversations held out by ml.conv_data (test_icfd_heldout). For ICFD, "violation" is the moment its verdict turns
YES (the first request that breaches security), so seconds-to-warn can be negative: warned before the ask.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from engine.listener.conversation import LEVELS, Accumulator
from engine.listener.rules import ASSETS

ROOT = Path(__file__).resolve().parents[2]
CONV = ROOT / "data" / "conv"
TARGET = {"t_watch": 0.10, "t_warn": 0.03, "t_scam": 0.005}
TRUSTED = {"t_watch": 0.03, "t_warn": 0.005, "t_scam": 0.001}
BASE_CFG = {
    "smooth": 2,
    "scam_run": 2,
    "why_rise": 0.15,
    "trusted_context": ["caller_verified", "known_contact"],
    "warn_context": ["caller_check_failed", "remote_app_opened"],
    "scam_context": ["remote_app_opened", "caller_check_failed", "video_call_unknown", "international_number"],
    "shown_context": ["remote_app_opened", "caller_check_failed", "video_call_unknown", "international_number", "long_call", "synthetic_voice"],
}


def calls(df: pd.DataFrame):
    """(group, source, case_type, is_scam, [(t, p, label)]) per call, in order, repeated moments dropped."""
    df = df.sort_values(["group", "t"])
    for g, d in df.groupby("group", sort=False):
        d = d[d["text"] != d["text"].shift()]
        is_scam = bool(d["label"].max() == 1) if d["source"].iloc[0] != "icfd" else "Fraud" in str(d["case_type"].iloc[0]).replace("_", " ")
        yield (
            g,
            d["source"].iloc[0].replace("+typos", ""),
            str(d["case_type"].iloc[0]).replace("_", " "),
            is_scam,
            list(zip(d["t"], d["p"], d["label"], strict=True)),
        )


def stats(ps: list[float], smooth: int, run: int) -> tuple[float, float]:
    """The highest smoothed p and the highest p held for `run` moments in a row, over the call."""
    a = np.asarray(ps, dtype=float)
    s = np.convolve(a, np.ones(smooth) / smooth, mode="full")[: len(a)]
    s[: smooth - 1] = [a[: i + 1].mean() for i in range(min(smooth - 1, len(a)))]
    r = np.array([a[max(0, i - run + 1) : i + 1].min() if i >= run - 1 else -1.0 for i in range(len(a))])
    return float(s.max()), float(r.max())


def calibrate() -> dict:
    df = pd.read_parquet(CONV / "dev.scored.parquet")
    genuine = {"icfd": [], "ours": []}
    for _, src, _, is_scam, seq in calls(df):
        if not is_scam:
            genuine["icfd" if src == "icfd" else "ours"].append(stats([p for _, p, _ in seq], BASE_CFG["smooth"], BASE_CFG["scam_run"]))
    cfg = dict(BASE_CFG)

    def cut(share: float, k: int) -> float:
        # all genuine dev calls as one pool (taking the stricter group instead let 12 copies of one template of ours,
        # relatives warning each other about scams, set every threshold; that failure is reported, not hidden)
        return round(float(np.quantile([x[k] for v in genuine.values() for x in v], 1 - share)), 4)

    for name, tgt in (("main", TARGET), ("trusted", TRUSTED)):
        th = {"t_watch": cut(tgt["t_watch"], 0), "t_warn": cut(tgt["t_warn"], 0), "t_scam": cut(tgt["t_scam"], 1)}
        # never out of order: watch ≤ warn ≤ scam
        th["t_warn"] = max(th["t_warn"], th["t_watch"])
        th["t_scam"] = max(th["t_scam"], th["t_warn"])
        if name == "main":
            cfg |= th
        else:
            cfg["trusted"] = th
    cfg = {
        "version": 1,
        "about": "The call accumulator (engine/listener/conversation.py, data/listen/Conversation.kt): thresholds on the conversation model's p, "
        "set on dev calls only (ml/eval/conv_eval.py) so that 10% / 3% / 0.5% of genuine dev calls ever reach watch / warn / scam "
        "(trusted caller: 3% / 0.5% / 0.1%).",
        "dev_genuine_calls": {k: len(v) for k, v in genuine.items()},
    } | cfg
    (ASSETS / "conv.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(cfg, indent=1))
    return cfg


def replay(seq: list[tuple], cfg: dict) -> dict:
    acc = Accumulator(cfg=cfg)
    first: dict[str, float] = {}
    for t, p, _ in seq:
        lvl = acc.feed(p)
        for name in ("watch", "warn", "scam"):
            if name not in first and LEVELS.index(lvl) >= LEVELS.index(name):
                first[name] = t
    return first


def rate(k: int, n: int) -> dict:
    return {"k": k, "n": n, "rate": round(k / n, 4) if n else None}


def measure() -> dict:
    cfg = json.loads((ASSETS / "conv.json").read_text(encoding="utf-8"))
    out: dict = {"thresholds": {k: cfg[k] for k in ("t_watch", "t_warn", "t_scam")}, "sets": {}}
    for f in sorted(CONV.glob("test_*.scored.parquet")):
        name = f.name.removesuffix(".scored.parquet")
        df = pd.read_parquet(f)
        groups: dict[tuple, list] = {}
        for _, src, ct, is_scam, seq in calls(df):
            first = replay(seq, cfg)
            viol = next((t for t, _, y in seq if y == 1), None) if src == "icfd" and is_scam else None
            key = (src, ct if src == "icfd" else ("scam" if is_scam else "harmless"))
            groups.setdefault(key, []).append((is_scam, first, viol, seq[-1][0]))
        res = {}
        for (src, ct), rows in sorted(groups.items()):
            is_scam = rows[0][0]
            r = {"calls": len(rows), "scam": is_scam}
            for lvl in ("watch", "warn", "scam"):
                r[f"reached_{lvl}"] = rate(sum(lvl in fr for _, fr, _, _ in rows), len(rows))
            if is_scam:
                warn_t = [fr["warn"] for _, fr, _, _ in rows if "warn" in fr]
                r["median_t_to_warn"] = float(np.median(warn_t)) if warn_t else None
                rel = [fr["warn"] - v for _, fr, v, _ in rows if "warn" in fr and v is not None]
                if rel:
                    r["median_s_warn_after_violation"] = float(np.median(rel))
                    r["warned_before_violation"] = rate(sum(x < 0 for x in rel), len(rel))
            res[f"{src} / {ct}"] = r
        out["sets"][name] = res
    (ROOT / "docs" / "results_conv.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    write_markdown(out)
    for name, res in out["sets"].items():
        print(f"\n{name}")
        for k, r in res.items():
            extra = f" median t→warn {r.get('median_t_to_warn')} after-violation {r.get('median_s_warn_after_violation')}" if r["scam"] else ""
            print(f"  {k:55} n={r['calls']:5} warn {r['reached_warn']['rate']} scam {r['reached_scam']['rate']}{extra}")
    return out


NAMES = {
    "test_icfd": "ICFD-31k test split (scam calls only)",
    "test_icfd_unseen": "ICFD-31k unseen scam types (cross-domain split)",
    "test_icfd_heldout": "ICFD-31k held-out conversations (genuine and scam calls)",
    "test_ours": "Our held-out sets (calls fed turn by turn; messages as one segment)",
}


def pct(r: dict) -> str:
    return "–" if r["rate"] is None else f"{100 * r['rate']:.1f}% ({r['k']}/{r['n']})"


def write_markdown(out: dict) -> None:
    from ml.eval.metrics import wilson

    L = [
        "<!-- generated by python -m ml.eval.conv_eval measure: do not edit by hand -->",
        "",
        f"Thresholds on the conversation model's p (set on dev only): watch {out['thresholds']['t_watch']}, "
        f"warn {out['thresholds']['t_warn']}, scam {out['thresholds']['t_scam']}.",
        "",
    ]
    for name, res in out["sets"].items():
        L += [
            f"**{NAMES.get(name, name)}**",
            "",
            "| Calls | n | Reached amber (warn) | Reached red (scam) | Median time to amber | Amber before the ask |",
            "|---|---|---|---|---|---|",
        ]
        for k, r in res.items():
            lo, hi = wilson(r["reached_warn"]["k"], r["reached_warn"]["n"])
            unit = "s" if k.startswith("icfd") else " turns"
            t = f"{r['median_t_to_warn']:.0f}{unit}" if r.get("median_t_to_warn") is not None else "–"
            before = pct(r["warned_before_violation"]) if "warned_before_violation" in r else "–"
            kind = "scam" if r["scam"] else "genuine"
            L.append(f"| {k} ({kind}) | {r['calls']} | {pct(r['reached_warn'])} [{100 * lo:.0f}–{100 * hi:.0f}%] | {pct(r['reached_scam'])} | {t} | {before} |")
        L.append("")
    for name, title, how in (
        ("kit_conv.json", "Spot-check kit with the conversation check (data/kit: 30 public held-out items)", "ml.eval.kit data/kit --json models/eval/kit_conv.json"),
        ("asr_bakeoff_conv.json", "Audio end to end with the conversation check (our 59 spoken calls, fed segment by segment)",
         "ml.eval.asr_bakeoff --models omnilingual_300m --check conv --out models/eval/asr_bakeoff_conv.json"),
    ):  # fmt: skip
        f = ROOT / "models" / "eval" / name
        L += [f"**{title}** (`python -m {how}`)", ""]
        L += [json.loads(f.read_text(encoding="utf-8")).get("markdown", "_see the json_"), ""] if f.exists() else ["_Not run on this machine yet._", ""]
    L.append("<!-- end conv_eval -->")
    md = ROOT / "docs" / "RESULTS.md"
    text = md.read_text(encoding="utf-8")
    a, b = "<!-- generated by python -m ml.eval.conv_eval measure: do not edit by hand -->", "<!-- end conv_eval -->"
    if a in text and b in text:
        text = text[: text.index(a)] + "\n".join(L) + text[text.index(b) + len(b) :]
        md.write_text(text, encoding="utf-8")
    else:
        print("\n".join(L))


def basic() -> dict:
    """The old decision path (basic mode: cue rules + the n-gram classifier through fusion) on the same held-out ICFD
    calls, fed turn by turn, for the old-vs-new table."""
    from engine.listener.analyzer import LiveCall
    from ml.conv_data import ICFD, icfd_turns, part

    out = {}
    for name, split, keep in (("test_icfd", "test", None), ("test_icfd_unseen", "cross_domain", None), ("test_icfd_heldout", "train", "test")):
        cols = ["conversation_uid", "chunk_timestamp", "cumulative_transcript_json", "cumulative_text", "case_type"]
        df = pd.concat([pd.read_parquet(f, columns=cols) for f in sorted(ICFD.glob(f"{split}-*.parquet"))], ignore_index=True)
        if keep:
            df = df[df["conversation_uid"].map(part) == keep]
        df = df.sort_values("chunk_timestamp").drop_duplicates("conversation_uid", keep="last")
        res: dict[str, list] = {}
        for _, r in df.iterrows():
            c, seen = LiveCall(), set()
            for t in icfd_turns(r):
                lvl = c.feed(t)
                seen.add(lvl)
            ct = str(r["case_type"]).replace("_", " ")
            res.setdefault(f"icfd / {ct}", []).append(c.prev)
        out[name] = {
            k: {"calls": len(v), "reached_warn": rate(sum(x in ("warn", "scam") for x in v), len(v)), "reached_scam": rate(sum(x == "scam" for x in v), len(v))}
            for k, v in sorted(res.items())
        }
    (ROOT / "docs" / "results_basic_icfd.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    for name, res in out.items():
        print(name)
        for k, r in res.items():
            print(f"  {k:45} n={r['calls']:5} warn {r['reached_warn']['rate']} scam {r['reached_scam']['rate']}")
    return out


if __name__ == "__main__":
    {"calibrate": calibrate, "measure": measure, "basic": basic}[sys.argv[1]]()
