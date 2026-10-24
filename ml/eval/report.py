"""Merge benchmark and IndiaCall results into models/metrics.json for the metrics page.

python -m ml.eval.report --indiacall test [--model add-wav2vec-large+add-xls-r-1b]

Only the benchmarks of one S1 version go in: the engine's model, which by default is the one
benchmarked most recently. models/eval/ keeps older models' runs for docs/ML.md, but the
metrics page must not show them as the running detector's numbers. Tagged runs
(`benchmark --tag before`) are snapshots for comparison and stay out too.

The "phone_mic" section answers the judges' test (an AI voice played from a laptop into the
phone): simulated over-the-air channels per generator family, false alarms on genuine speech
through the same phone, and the real recordings (ReplayDF's speaker-to-mic replays, and our
own phone-mic recordings from data/ota once they exist).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import Counter, defaultdict

import numpy as np

from engine.config import settings
from engine.fusion import TIERS
from ml.augment.telephony import OTA_CHANNELS
from ml.eval.indiacall_sim import CLI_KINDS, DATA, LEVELS, PLACEHOLDER_LAG, REGISTERED
from ml.eval.metrics import wilson
from ml.tts_sets import family

EVAL = settings.models_dir / "eval"
LANG = {"en": "English", "hi": "Hindi", "hinglish": "Hinglish"}
MAX_GENUINE_STEPUP = 0.05  # deck target, for genuine calls from the registered number


def cli_of(r: dict) -> str:
    """registered | other; runs from before cli_kind was recorded fall back to the number itself."""
    return r["plan"].get("cli_kind") or ("registered" if r["plan"]["cli"] == REGISTERED else "other")


def stepped_up(r: dict) -> bool:
    return r["final_tier"] in ("AMBER", "RED")


def reached(r: dict) -> str:
    """Highest tier the agent saw during the call (tiers only rise, so normally the final one)."""
    seen = [t for t in [*r.get("tiers_seen", []), r.get("final_tier")] if t in TIERS]
    return max(seen, key=TIERS.index) if seen else "none"


def rate_row(rows: list[dict], hit, **extra) -> dict:
    k = sum(1 for r in rows if hit(r))
    n = len(rows)
    return {**extra, "n": n, "k": k, "rate": k / n if n else 0.0, "ci": list(wilson(k, n))}


def ci_text(row: dict) -> str:
    return f"{row['k']} of {row['n']} ({row['rate']:.1%}, 95% CI {row['ci'][0]:.1%} to {row['ci'][1]:.1%})"


def genuine_rows(gen: list[dict]) -> list[dict]:
    """Genuine calls by caller number. The 5% target is for the registered number; calls from another
    number get a liveness check by design (S4's CLI_MISMATCH), which is shown here rather than hidden."""
    return [
        {
            **rate_row([r for r in gen if cli_of(r) == kind], stepped_up, cli_kind=kind, label=f"Genuine, {label}"),
            "executed": sum(r["executed"] for r in gen if cli_of(r) == kind),
        }
        for kind, label in CLI_KINDS.items()
    ]


def detection_rows(att: list[dict]) -> list[dict]:
    """Detection only, per level and caller-number variant: how many attacks the agent saw as AMBER or RED,
    and how many ended GREEN, i.e. the calls a voice-only bank would have approved."""
    out = []
    for lvl in LEVELS:
        for kind in CLI_KINDS:
            rs = [r for r in att if r["plan"]["level"] == lvl and cli_of(r) == kind]
            if not rs:
                continue
            row = rate_row(rs, lambda r: reached(r) in ("AMBER", "RED"), level=lvl, cli_kind=kind, spoofed_cli=kind == "registered")
            row["red"] = sum(reached(r) == "RED" for r in rs)
            row["ended_green"] = sum(r["final_tier"] == "GREEN" for r in rs)
            out.append(row)
    return out


def generator_rows(att: list[dict]) -> list[dict]:
    """Detection per clone generator, on L1-L3 calls that spoof the registered number: no caller-ID
    flag, so the tier comes from the voice signals alone. This is the "which clone beat you" table."""
    out = []
    voice_only = [r for r in att if r["plan"]["level"] in ("L1", "L2", "L3") and cli_of(r) == "registered"]
    for g in sorted({r["plan"]["generator"] for r in voice_only}):
        rs = [r for r in voice_only if r["plan"]["generator"] == g]
        row = rate_row(rs, lambda r: reached(r) in ("AMBER", "RED"), generator=g, levels=sorted({r["plan"]["level"] for r in rs}))
        row["red"] = sum(reached(r) == "RED" for r in rs)
        row["ended_green"] = sum(r["final_tier"] == "GREEN" for r in rs)
        out.append(row)
    return out


def summarise(results: list[dict]) -> dict:
    rows = [r for r in results if not r.get("error")]
    errors = [r for r in results if r.get("error")]
    gen = [r for r in rows if r["plan"]["level"] == "genuine"]
    att = [r for r in rows if r["plan"]["level"] != "genuine"]
    reg = [r for r in gen if cli_of(r) == "registered"]
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
                "by_cli": dict(Counter(cli_of(r) for r in rs)),
            }
        )

    by_cli = genuine_rows(gen)
    reg_row = next(g for g in by_cli if g["cli_kind"] == "registered")
    overall = reg_row["rate"]
    # fairness is judged on registered-number calls, where a step-up is a real false alarm
    fairness = []
    for lang in sorted({r["language"] for r in reg}):
        g = [r for r in reg if r["language"] == lang]
        row = rate_row(g, stepped_up)
        fairness.append({"group": LANG.get(lang, lang), "n": row["n"], "fpr": row["rate"], "ci": row["ci"]})
    by_spk = defaultdict(list)
    for r in reg:
        by_spk[r["plan"]["speaker"]].append(r)
    for spk, g in sorted(by_spk.items()):
        row = rate_row(g, stepped_up)
        fairness.append({"group": f"Speaker {spk}", "n": row["n"], "fpr": row["rate"], "ci": row["ci"]})

    misses = []
    for r in att:
        if r["final_tier"] != "RED":
            misses.append(
                {
                    "id": r["plan"]["id"],
                    "level": r["plan"]["level"],
                    "cli_kind": cli_of(r),
                    "language": LANG.get(r["language"], r["language"]),
                    "tier": r["final_tier"] or "none",
                    "why": f"generator {r['plan']['generator']}; {'spoofed registered number' if cli_of(r) == 'registered' else 'own number'}; "
                    f"S1 call score {((r.get('features') or {}).get('s1') or 0):.2f}; liveness {'passed' if (r.get('liveness') or {}).get('passed') else 'failed'}"
                    + ("; change was made" if r["executed"] else "; change still blocked by app approval"),
                }
            )
    # a genuine call from another number is expected to reach AMBER (one step for the unknown number); RED is a miss
    for r in gen:
        if (cli_of(r) == "registered" and stepped_up(r)) or r["final_tier"] == "RED":
            misses.append(
                {
                    "id": r["plan"]["id"],
                    "level": "genuine",
                    "cli_kind": cli_of(r),
                    "language": LANG.get(r["language"], r["language"]),
                    "tier": r["final_tier"],
                    "why": "genuine caller given an extra check: " + ", ".join(r.get("reasons") or []),
                }
            )

    detection = detection_rows(att)
    spoofed = [d for d in detection if d["spoofed_cli"] and d["level"] in ("L1", "L2", "L3")]
    p95_first = float(np.percentile(first, 95)) if first else None
    targets = [
        {
            "name": "Risky changes approved for attackers L1 to L4",
            "target": f"0 of {len(att)}",
            "result": f"{len(approved)} of {len(att)}",
            "pass": len(approved) == 0,
        },
        {
            "name": f"Genuine callers on their registered number given an extra check ({reg_row['n']} calls)",
            "target": f"{MAX_GENUINE_STEPUP:.0%} or fewer",
            "result": ci_text(reg_row),
            "pass": (overall <= MAX_GENUINE_STEPUP) if reg_row["n"] else None,
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
    if spoofed:
        n = sum(d["n"] for d in spoofed)
        green = sum(d["ended_green"] for d in spoofed)
        targets.append(
            {
                "name": "L1 to L3 with spoofed caller ID (voice signals only) that ended GREEN",
                "target": "—",
                "result": f"{green} of {n}",
                "pass": None,
            }
        )
    worst = max((f["fpr"] for f in fairness if not f["group"].startswith("Speaker")), default=0)
    targets.append(
        {
            "name": "False alarms per language vs overall (registered number)",
            "target": "under 2× overall",
            "result": f"worst {worst:.0%} vs {overall:.0%}",
            "pass": (worst <= 2 * overall) if overall > 0 else worst == 0,
        }
    )
    return {
        "targets": targets,
        "levels": levels,
        "genuine": {"calls": len(gen), "stepped_up": sum(stepped_up(r) for r in gen), "rate": overall, "by_cli": by_cli},
        "detection": detection,
        "by_generator": generator_rows(att),
        "first_tier_s": {"p50": float(np.median(first)), "p95": p95_first} if first else None,
        "fairness": fairness,
        "misses": misses,
        "errors": len(errors),
    }


FAMILY = {
    "commercial": "Commercial TTS (Microsoft, Google, ElevenLabs, ...)",
    "open": "Open TTS and voice clones",
    "unknown": "Unknown generators (In-the-Wild)",
}
REAL = {"replaydf.csv": "replaydf", "ota_real.csv": "recorded"}


def _ci_row(k: int, n: int, **extra) -> dict:
    return {**extra, "n": n, "k": k, "rate": k / n if n else 0.0, "ci": list(wilson(k, n))}


def phone_mic_section(runs: list[dict]) -> dict | None:
    """Over-the-air numbers from benchmark runs: detection per generator family and per generator
    on the simulated "ota+" channels (pooled over sets), genuine false alarms on those channels per
    set, and every condition of the real-recording sets."""
    fam: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    gens: dict[tuple[str, str], dict] = {}
    genuine, real = [], []
    for d in runs:
        kind = next((v for k, v in REAL.items() if str(d.get("manifest", "")).replace("\\", "/").endswith(k)), None)
        for r in d["results"]:
            if kind:
                real.append(
                    {
                        "set": d["set"],
                        "kind": kind,
                        "condition": r["condition"],
                        **{k: r.get(k) for k in ("n_bona", "n_spoof", "eer", "false_alarm_amber", "false_alarm_amber_ci", "detect_amber", "detect_red")},
                        "by_generator": r.get("by_generator", []),
                    }
                )
                continue
            if not r["condition"].startswith("ota+"):
                continue
            if r.get("n_bona"):
                genuine.append(_ci_row(round(r["false_alarm_amber"] * r["n_bona"]), r["n_bona"], set=d["set"], condition=r["condition"]))
            for g in r.get("by_generator", []):
                f = fam[(r["condition"], g.get("family") or family(g["generator"]))]
                f[0] += g["k"]
                f[1] += g["n"]
                e = gens.setdefault((r["condition"], g["generator"]), {"k": 0, "n": 0, "red": 0.0, "sets": set()})
                e["k"] += g["k"]
                e["n"] += g["n"]
                e["red"] += g["detect_red"] * g["n"]
                e["sets"].add(d["set"])
    if not (fam or real or genuine):
        return None

    def order(key: tuple[str, str]) -> tuple:  # G.711 first: the path a phone call takes
        return (OTA_CHANNELS.index(key[0]) if key[0] in OTA_CHANNELS else len(OTA_CHANNELS), key)

    families = [_ci_row(k, n, condition=c, family=f, label=FAMILY.get(f, f)) for (c, f), (k, n) in sorted(fam.items(), key=lambda kv: order(kv[0]))]
    generators = [
        _ci_row(e["k"], e["n"], condition=c, generator=g, family=family(g), sets=sorted(e["sets"]), red=round(e["red"] / e["n"], 4) if e["n"] else 0.0)
        for (c, g), e in sorted(gens.items(), key=lambda kv: order(kv[0]))
    ]
    worst = max((g["rate"] for g in genuine), default=None)
    return {
        "families": families,
        "generators": generators,
        "genuine": genuine,
        "real": real,
        "max_genuine_amber": MAX_GENUINE_STEPUP,
        "genuine_target_met": (worst <= MAX_GENUINE_STEPUP) if worst is not None else None,
    }


def indiacall_section(run: str) -> dict | None:
    p = EVAL / f"indiacall_{run}.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text())
    out = summarise(d["results"])
    out["human_lags"] = d.get("human_lags")
    return out


def lag_note(ic: dict | None) -> str:
    """Say what the genuine reply delays actually were: measured on live calls, or a placeholder."""
    lags = (ic or {}).get("human_lags")
    if lags is None:  # run from before the simulator recorded this; judge by the file as it is now
        p = DATA / "human_lags.json"
        lags = {"measured": len(json.loads(p.read_text())) if p.exists() else 0}
    if lags.get("measured"):
        how = f"sampled from {lags['measured']} reply delays measured on live genuine calls (data/indiacall/human_lags.json)"
    else:
        how = f"sampled from a placeholder distribution ({PLACEHOLDER_LAG}), because data/indiacall/human_lags.json did not exist yet"
    return (
        "IndiaCall: teammates' and volunteers' consented voices and the teammates' clones, streamed through the live engine over G.711. "
        f"Genuine reply delays are {how}; attacker delays come from the attack model. Audio, words, scoring, policy and passkey signatures are real."
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--indiacall", default="test")
    ap.add_argument("--model", default=None, help="S1 version to report (default: the most recently benchmarked)")
    a = ap.parse_args()
    runs = [json.loads(p.read_text()) for p in sorted(EVAL.glob("bench_*.json"), key=lambda p: p.stat().st_mtime)]
    runs = [d for d in runs if not d.get("tag")]
    model = a.model or (runs[-1].get("model") if runs else None)
    runs = [d for d in runs if d.get("model") == model]
    benchmarks = [{k: v for k, v in r.items() if k != "by_generator"} for d in runs for r in d["results"]]
    ic = indiacall_section(a.indiacall)
    fusion = settings.models_dir / "fusion.json"
    notes = [
        "Detector EERs use the first 4 s of each clip, passed through the named phone channel (ffmpeg codecs).",
        lag_note(ic),
        "Genuine calls from another number are reported apart from the registered number: the policy gives them a liveness check by design, so they are expected to reach AMBER and are not counted against the 5% target.",
        "Detection only: attacks that spoof the registered number carry no caller-ID flag, so their tier comes from the voice signals alone.",
        "Speakers whose voices were cloned were never in S1 training data.",
        'Phone mic, played through a speaker: "ota" channels are simulated (ml/augment/telephony.py over_the_air): a small loudspeaker '
        "15 cm to 1 m from the phone in a synthetic room, room noise, the phone's noise suppressor and AGC, then the codec. Genuine clips "
        "in those channels are spoken into the same phone from 3 to 80 cm, without the loudspeaker. ReplayDF rows are real re-recordings "
        "in which genuine speech was replayed through the loudspeaker too, so their false alarms are a worst case.",
    ]
    if ic and ic.get("errors"):
        notes.append(f"{ic['errors']} simulated calls failed to run and are excluded.")
    out = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "model": {"s1": model or "unknown", "fusion": json.loads(fusion.read_text()).get("source", "fitted") if fusion.exists() else "default weights"},
        "benchmarks": benchmarks,
        "phone_mic": phone_mic_section(runs),
        "indiacall": ic,
        "notes": notes,
    }
    (settings.models_dir / "metrics.json").write_text(json.dumps(out, indent=2))
    print("wrote models/metrics.json")


if __name__ == "__main__":
    main()
