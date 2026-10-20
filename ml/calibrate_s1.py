"""Fit S1's score calibration (Platt scaling) on the dev split through phone channels.

    python -m ml.calibrate_s1 [--checkpoint models/s1_sls_phone.pt]
    python -m ml.calibrate_s1 --checkpoint models/s1_add_mms300m.pt,models/s1_sls_phone.pt   (ensemble)
    -> models/s1_calibration.json (keyed to the checkpoint's version, "v1+v2" for an ensemble)

For an ensemble the same logistic regression takes one log-odds column per model, so it
learns how much to trust each one on phone audio.

The raw XLS-R+SLS output is very overconfident (real speech often gets P(fake) > 0.9),
so the GREEN/AMBER/RED cut-offs only mean something after this step. Dev clips are
speaker-disjoint from training and never include IndiaCall or the public test sets.
"""

from __future__ import annotations

import argparse
import json
import random
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from sklearn.linear_model import LogisticRegression
from tqdm import tqdm

from engine.config import settings
from engine.signals.s1_synth import S1Detector
from ml.augment.telephony import channel, load_audio
from ml.eval.metrics import eer
from ml.s1_data import read

CHANNELS = ["g711u", "amrnb_12k2", "opus_12k", "gsm", "clean"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", default=str(settings.s1_checkpoint))
    ap.add_argument("--dev", default="data/manifests/dev.csv")
    ap.add_argument("--n", type=int, default=1500)
    a = ap.parse_args()
    det = S1Detector()
    det.load(a.checkpoint)

    rows = read(a.dev)
    rng = random.Random(0)
    bona = [r for r in rows if r["label"] == "bonafide"]
    spoof = [r for r in rows if r["label"] != "bonafide"]
    rows = rng.sample(bona, min(len(bona), a.n // 2)) + rng.sample(spoof, min(len(spoof), a.n // 2))

    def prep(i_r):
        i, r = i_r
        x = load_audio(r["path"])[: settings.window_samples]
        return channel(x, CHANNELS[i % len(CHANNELS)])

    z, y = [], []
    with ThreadPoolExecutor(8) as pool:
        for i in tqdm(range(0, len(rows), 16), desc="dev scoring"):
            chunk = list(enumerate(rows[i : i + 16], i))
            wav = list(pool.map(prep, chunk))
            z.append(det.features(wav))
            y += [0 if r["label"] == "bonafide" else 1 for _, r in chunk]
    z, y = np.clip(np.concatenate(z), -60, 60), np.array(y)
    clf = LogisticRegression(C=10.0).fit(z, y)
    W, B = [float(w) for w in clf.coef_[0]], float(clf.intercept_[0])
    p = 1 / (1 + np.exp(-(z @ np.array(W) + B)))
    e, _ = eer(p[y == 0], p[y == 1])
    out = {
        "version": det.version,
        "w": W,
        "a": W[0],  # single-model files written before ensembles read "a"
        "b": B,
        "n": int(len(y)),
        "dev_eer": round(e, 4),
        "genuine_above_0.3": round(float(np.mean(p[y == 0] >= 0.3)), 4),
        "genuine_above_0.7": round(float(np.mean(p[y == 0] >= 0.7)), 4),
        "spoof_above_0.7": round(float(np.mean(p[y == 1] >= 0.7)), 4),
        "channels": CHANNELS,
    }
    path = settings.models_dir / "s1_calibration.json"
    allc = json.loads(path.read_text()) if path.exists() else {}
    if "version" in allc:  # old single-entry format
        allc = {allc["version"]: allc}
    allc[det.version] = out
    path.write_text(json.dumps(allc, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
