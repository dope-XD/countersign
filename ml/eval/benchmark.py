"""S1 benchmark on public test sets, across phone channels.

    python -m ml.eval.benchmark --manifest data/manifests/asv19_eval.csv --name "ASVspoof 2019 LA eval" \
        --channels clean,g711u,amrnb_12k2,opus_12k --limit 2000 --published 0.0287

    python -m ml.eval.benchmark --manifest data/manifests/dev.csv --sources fleurs_hi,indicsynth --name "Hindi dev" \
        --channels g711u,amrnb_12k2,g711u+loss+noise --checkpoint models/s1_add_mms300m.pt

    python -m ml.eval.benchmark --manifest data/manifests/tts_stock.csv --name "Stock AI voices"         --channels clean,g711u,ota+g711u,ota+amrnb_12k2,ota+g711u+noise --limit 0

Manifest CSV columns: path,label (bonafide|spoof)[,speaker,language,generator,source,split].
Channels may add "+noise" / "+loss", or start with "ota+" (played from a speaker into a phone
mic; genuine rows are spoken into the phone instead), see ml.augment.telephony.channel.
Besides EER, every result reports what the engine would actually do with the calibrated
window score: the share of genuine clips at or above the AMBER and RED cut-offs (false
alarms) and of fake clips at or above them (detections), and the detections per generator
with 95% Wilson intervals. A genuine-only manifest gives false-alarm rates alone.
Writes models/eval/bench_<slug>__<model>.json, which ml.eval.report merges into metrics.json.
`--tag before` writes bench_<slug>__<model>__before.json instead, which the report leaves out:
a snapshot to compare a new calibration against.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import time
import zlib
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from tqdm import tqdm

from engine.config import settings
from engine.signals.s1_synth import detector
from ml.augment.telephony import channel, load_audio
from ml.eval.metrics import detection_at_far, eer, wilson
from ml.s1_data import read
from ml.tts_sets import family

OUT = settings.models_dir / "eval"


def read_manifest(path: str, limit: int | None, seed: int = 0, sources: list[str] | None = None, split: str | None = None) -> list[dict]:
    rows = read(path)
    if sources:
        rows = [r for r in rows if r.get("source") in sources]
    if split:
        rows = [r for r in rows if r.get("split") == split]
    if limit and len(rows) > limit:
        rng = random.Random(seed)
        bona = [r for r in rows if r["label"] == "bonafide"]
        spoof = [r for r in rows if r["label"] != "bonafide"]
        nb = min(len(bona), limit // 2)
        rows = rng.sample(bona, nb) + rng.sample(spoof, min(len(spoof), limit - nb))
    return rows


def prep(row: dict, ch: str) -> np.ndarray:
    x = load_audio(row["path"])
    x = x[: settings.window_samples]  # first 4 s, as the original evaluation does
    # same noise, losses and rooms for every model
    return channel(x, ch, seed=zlib.crc32(row["path"].encode()), genuine=row["label"] == "bonafide")


def rates(bona: np.ndarray, spoof: np.ndarray) -> dict:
    """EER where both classes exist, plus behaviour at the engine's tier cut-offs."""
    out: dict = {"n_bona": int(len(bona)), "n_spoof": int(len(spoof))}
    if len(bona) and len(spoof):
        e, thr = eer(bona, spoof)
        det, _ = detection_at_far(bona, spoof, 0.01)
        out |= {"eer": round(e, 4), "threshold": round(thr, 4), "detect_at_1pct_far": round(det, 4)}
    else:
        out |= {"eer": None, "threshold": None, "detect_at_1pct_far": None}
    for tier, cut in (("amber", settings.amber_at), ("red", settings.red_at)):
        out[f"false_alarm_{tier}"] = round(float(np.mean(bona >= cut)), 4) if len(bona) else None
        out[f"detect_{tier}"] = round(float(np.mean(spoof >= cut)), 4) if len(spoof) else None
    if len(bona):
        out["false_alarm_amber_ci"] = [round(c, 4) for c in wilson(int(np.sum(bona >= settings.amber_at)), len(bona))]
    return out


def by_generator(rows: list[dict], scores: np.ndarray) -> list[dict]:
    """Fakes per generator that reach AMBER and RED, with a 95% Wilson interval on AMBER."""
    out = []
    for g in sorted({r.get("generator") or "unknown" for r in rows if r["label"] != "bonafide"}):
        s = np.array([x for r, x in zip(rows, scores, strict=True) if r["label"] != "bonafide" and (r.get("generator") or "unknown") == g])
        k = int(np.sum(s >= settings.amber_at))
        out.append(
            {
                "generator": g,
                "family": family(g),
                "n": len(s),
                "k": k,
                "detect_amber": round(k / len(s), 4),
                "ci": [round(c, 4) for c in wilson(k, len(s))],
                "detect_red": round(float(np.mean(s >= settings.red_at)), 4),
            }
        )
    return out


def run(
    manifest: str,
    name: str,
    channels: list[str],
    limit: int | None,
    published: float | None,
    batch: int = 8,
    checkpoint: str | None = None,
    sources: list[str] | None = None,
    split: str | None = None,
    tag: str | None = None,
) -> dict:
    detector.load(checkpoint)
    if detector.model is None:
        raise SystemExit("S1 is not a real model; convert a checkpoint first (ml/port_sls_checkpoint.py or ml/port_antideepfake.py)")
    rows = read_manifest(manifest, limit, sources=sources, split=split)
    results = []
    for ch in channels:
        t0 = time.time()
        scores: list[float] = []
        with ThreadPoolExecutor(8) as pool:
            for i in tqdm(range(0, len(rows), batch), desc=f"{name} [{ch}]"):
                chunk = rows[i : i + batch]
                wav = list(pool.map(prep, chunk, [ch] * len(chunk)))
                scores += [r.p_synthetic for r in detector.score(wav)]
        labels = np.array([r["label"] == "bonafide" for r in rows])
        s = np.array(scores)
        results.append(
            {
                "set": name,
                "condition": ch,
                "model": detector.version,
                "calibrated": detector.calibrated,
                **rates(s[labels], s[~labels]),
                "by_generator": by_generator(rows, s),
                "published_eer": published if ch == "clean" else None,
                "seconds": round(time.time() - t0, 1),
            }
        )
        print(results[-1])
    calib = {"w": [round(float(w), 4) for w in detector.calib_w], "b": round(detector.calib_b, 4)}
    out = {
        "model": detector.version,
        "calibration": calib,
        "set": name,
        "manifest": manifest,
        "sources": sources,
        "split": split,
        "tag": tag,
        "results": results,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    (OUT / f"bench_{slug}__{detector.version}{'__' + tag if tag else ''}.json").write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--channels", default="clean,g711u,amrnb_12k2,opus_12k")
    ap.add_argument("--limit", type=int, default=2000)
    ap.add_argument("--published", type=float, default=None)
    ap.add_argument("--checkpoint", default=None)
    ap.add_argument("--sources", default=None, help="comma-separated manifest `source` values to keep")
    ap.add_argument("--split", default=None, help="keep only rows with this `split` (e.g. test)")
    ap.add_argument("--tag", default=None, help="snapshot name; tagged runs stay out of metrics.json")
    a = ap.parse_args()
    srcs = a.sources.split(",") if a.sources else None
    run(a.manifest, a.name, a.channels.split(","), a.limit or None, a.published, checkpoint=a.checkpoint, sources=srcs, split=a.split, tag=a.tag)
