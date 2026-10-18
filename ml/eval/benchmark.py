"""S1 benchmark on public test sets, across phone channels.

    python -m ml.eval.benchmark --manifest data/manifests/asv19_eval.csv --name "ASVspoof 2019 LA eval" \
        --channels clean,g711u,amrnb_12k2,opus_12k --limit 2000 --published 0.0287

Manifest CSV columns: path,label (bonafide|spoof)[,speaker,language,generator].
Writes models/eval/bench_<slug>.json, which ml.eval.report merges into metrics.json.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from tqdm import tqdm

from engine.config import settings
from engine.signals.s1_synth import detector
from ml.augment.telephony import channel, load_audio
from ml.eval.metrics import detection_at_far, eer
from ml.s1_data import read

OUT = settings.models_dir / "eval"


def read_manifest(path: str, limit: int | None, seed: int = 0) -> list[dict]:
    rows = read(path)
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
    return channel(x, ch)


def run(manifest: str, name: str, channels: list[str], limit: int | None, published: float | None, batch: int = 8, checkpoint: str | None = None) -> dict:
    detector.load(checkpoint)
    if detector.backend != "sls":
        raise SystemExit("S1 is not the real model; convert a checkpoint first (ml/port_sls_checkpoint.py)")
    rows = read_manifest(manifest, limit)
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
        e, thr = eer(s[labels], s[~labels])
        det, _ = detection_at_far(s[labels], s[~labels], 0.01)
        results.append(
            {
                "set": name,
                "condition": ch,
                "model": detector.version,
                "eer": round(e, 4),
                "threshold": round(thr, 4),
                "detect_at_1pct_far": round(det, 4),
                "n_bona": int(labels.sum()),
                "n_spoof": int((~labels).sum()),
                "published_eer": published if ch == "clean" else None,
                "seconds": round(time.time() - t0, 1),
            }
        )
        print(results[-1])
    out = {"model": detector.version, "set": name, "manifest": manifest, "results": results}
    OUT.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    (OUT / f"bench_{slug}__{detector.version}.json").write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--channels", default="clean,g711u,amrnb_12k2,opus_12k")
    ap.add_argument("--limit", type=int, default=2000)
    ap.add_argument("--published", type=float, default=None)
    ap.add_argument("--checkpoint", default=None)
    a = ap.parse_args()
    run(a.manifest, a.name, a.channels.split(","), a.limit, a.published, checkpoint=a.checkpoint)
