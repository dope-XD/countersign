"""Experiment: can S1 be made to hold up over the air without retraining the backbones?

    python -m ml.s1_head --n 3000   -> models/eval/s1_head.json

Four scorers on the same windows, all fitted on train.csv clips (each clip once through an
over-the-air channel and once through a calibration channel, ml/calibrate_s1.py's list):

  current    the committed calibration in models/s1_calibration.json
  ota_refit  the same Platt scaling refitted with the over-the-air channels (what
             `python -m ml.calibrate_s1` now does)
  ota_5pct   ota_refit with its bias moved so 5% of the fit set's genuine windows reach AMBER
  head       a small head on the frozen ensemble's pooled embeddings (the input of each
             AntiDeepfake model's final Linear: 1024 + 1280 dims, taken with forward hooks):
             standardise -> logistic regression; its AMBER cut-off also puts 5% of the fit
             set's genuine windows at AMBER

Each is judged on generators none of them saw: the stock AI voices (edge-tts, gTTS, Piper),
In-the-Wild, and ReplayDF's real replays (Bark, VITS, XTTS; IndicSynth's XTTS v2 is in train,
so that one is only partly held out). Two numbers per scorer: what the engine would do (genuine
and fake windows at the AMBER cut-off) and fakes caught at the false-alarm rate the current
calibration has on that set, so a scorer can't win by flagging more genuine audio.
A head would only become an ensemble member if it catches more held-out fakes at the same
false-alarm rate; it needs an engine change (a new S1 backend), so it is reported here first.
"""

from __future__ import annotations

import argparse
import json
import random
import zlib
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from tqdm import tqdm

from engine.config import settings
from engine.signals.s1_synth import detector
from ml.augment.telephony import OTA_CHANNELS, channel, load_audio
from ml.calibrate_s1 import CHANNELS
from ml.eval.benchmark import read_manifest
from ml.eval.metrics import eer, wilson
from ml.s1_data import read

FA_BUDGET = 0.05


def embedder():
    """windows -> (pooled embeddings of every member, raw spoof log-odds per member), via hooks."""
    import torch

    from engine.signals.sls_model import fit_length

    grabbed: list = []
    for m in detector.models:
        m.head.register_forward_hook(lambda mod, inp, out: grabbed.append(inp[0].float().cpu().numpy()))

    def run(windows):
        grabbed.clear()
        x = torch.stack([fit_length(torch.from_numpy(np.ascontiguousarray(w))) for w in windows]).to(detector.device)
        if detector.device == "cuda":
            x = x.half()
        cols = []
        with torch.inference_mode():
            for m in detector.models:
                out = m(x).float()
                cols.append((out[:, 0] - out[:, 1]).cpu().numpy())
        return np.concatenate(grabbed, axis=1), np.clip(np.stack(cols, axis=1), -60, 60)

    return run


def featurise(run, rows: list[dict], chans: list[str], desc: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Same seeds as ml.eval.benchmark, so the held-out windows match its runs."""

    def prep(i):
        r = rows[i]
        x = load_audio(r["path"])[: settings.window_samples]
        return channel(x, chans[i], seed=zlib.crc32(r["path"].encode()), genuine=r["label"] == "bonafide")

    embs, zs = [], []
    with ThreadPoolExecutor(8) as pool:
        for b in tqdm(range(0, len(rows), 8), desc=desc):
            e, z = run(list(pool.map(prep, range(b, min(b + 8, len(rows))))))
            embs.append(e)
            zs.append(z)
    y = np.array([r["label"] != "bonafide" for r in rows], dtype=int)
    return np.concatenate(embs), np.concatenate(zs), y


def sigmoid(z):
    return 1 / (1 + np.exp(-z))


def cut_for(p_genuine: np.ndarray, fa: float) -> float:
    """The lowest threshold at which at most `fa` of these genuine scores are at or above it."""
    s = np.sort(p_genuine)[::-1]
    k = int(np.floor(fa * len(s)))
    return float(np.nextafter(s[k], 1)) if k < len(s) else float(s[-1])


def judge(p: np.ndarray, y: np.ndarray, amber: float, ref_fa: float) -> dict:
    bona, spoof = p[y == 0], p[y == 1]
    k = int(np.sum(spoof >= amber))
    t = cut_for(bona, ref_fa)
    return {
        "genuine_at_amber": round(float(np.mean(bona >= amber)), 4),
        "fakes_at_amber": round(k / len(spoof), 4),
        "fakes_at_amber_ci": [round(c, 4) for c in wilson(k, len(spoof))],
        "eer": round(eer(bona, spoof)[0], 4),
        "fakes_at_current_fa": round(float(np.mean(spoof >= t)), 4),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=3000)
    a = ap.parse_args()
    detector.load("models/s1_add_w2vlarge.pt,models/s1_add_xlsr1b.pt")
    run = embedder()

    rng = random.Random(0)
    rows = read("data/manifests/train.csv")
    bona = [r for r in rows if r["label"] == "bonafide"]
    spoof = [r for r in rows if r["label"] != "bonafide"]
    tr = rng.sample(bona, min(len(bona), a.n // 2)) + rng.sample(spoof, min(len(spoof), a.n // 2))
    chans = [OTA_CHANNELS[i % len(OTA_CHANNELS)] for i in range(len(tr))] + [CHANNELS[i % len(CHANNELS)] for i in range(len(tr))]
    X, Z, y = featurise(run, tr + tr, chans, "fit")

    scorers = {"current": lambda e, z: sigmoid(z @ detector.calib_w + detector.calib_b)}
    platt = LogisticRegression(C=10.0).fit(Z, y)
    scorers["ota_refit"] = lambda e, z: platt.predict_proba(z)[:, 1]
    p_fit = platt.predict_proba(Z)[:, 1]
    shift = np.log(cut_for(p_fit[y == 0], FA_BUDGET) / (1 - cut_for(p_fit[y == 0], FA_BUDGET))) - np.log(settings.amber_at / (1 - settings.amber_at))
    scorers["ota_5pct"] = lambda e, z: sigmoid(platt.decision_function(z) - shift)
    head = make_pipeline(StandardScaler(), LogisticRegression(C=0.01, max_iter=3000)).fit(np.hstack([X, Z]), y)
    h_fit = head.predict_proba(np.hstack([X, Z]))[:, 1]
    h_shift = np.log(cut_for(h_fit[y == 0], FA_BUDGET) / (1 - cut_for(h_fit[y == 0], FA_BUDGET))) - np.log(settings.amber_at / (1 - settings.amber_at))
    scorers["head"] = lambda e, z: sigmoid(head.decision_function(np.hstack([e, z])) - h_shift)
    fit_stats = {k: judge(f(X, Z), y, settings.amber_at, FA_BUDGET) for k, f in scorers.items()}

    tests = [
        ("Stock AI voices", read_manifest("data/manifests/tts_stock.csv", None), ["g711u", *OTA_CHANNELS]),
        ("In-the-Wild", read_manifest("data/manifests/itw.csv", 1200), ["g711u", "ota+g711u"]),
        ("ReplayDF", read_manifest("data/manifests/replaydf.csv", None), ["clean", "g711u"]),
    ]
    held: dict = {}
    for name, rs, conds in tests:
        for c in conds:
            E, Zt, yt = featurise(run, rs, [c] * len(rs), f"{name} [{c}]")
            probs = {k: f(E, Zt) for k, f in scorers.items()}
            ref_fa = float(np.mean(probs["current"][yt == 0] >= settings.amber_at))
            held[f"{name} | {c}"] = {"current_fa": round(ref_fa, 4), "n_bona": int(np.sum(yt == 0)), "n_spoof": int(np.sum(yt == 1))} | {
                k: judge(p, yt, settings.amber_at, ref_fa) for k, p in probs.items()
            }
            print(name, c, json.dumps(held[f"{name} | {c}"]), flush=True)
    out = {
        "fit": {"n": len(y), "manifest": "data/manifests/train.csv", "channels": sorted(set(chans)), "stats": fit_stats},
        "ota_refit": {"w": platt.coef_[0].round(4).tolist(), "b": round(float(platt.intercept_[0]), 4), "b_5pct": round(float(platt.intercept_[0] - shift), 4)},
        "held_out": held,
    }
    path = settings.models_dir / "eval" / "s1_head.json"
    path.write_text(json.dumps(out, indent=2))
    print(json.dumps(out["fit"], indent=2))


if __name__ == "__main__":
    main()
