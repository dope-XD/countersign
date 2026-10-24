"""The on-phone voice-clone check: the first K transformer layers of AntiDeepfake W2V-Large (frozen) + a logistic head.

    python -m ml.voice_clone             # embed, pick K and the threshold on dev, export ONNX int8, score held-out sets
    python -m ml.voice_clone --quick     # fewer clips

Why this shape: the middle layers of a wav2vec 2.0 model carry most of what separates real from synthetic speech, and
cutting the network there makes it small enough for a phone (arXiv 2606.30780 reports layer 7 of W2V2 at 8.4%
out-of-domain EER in a browser). We sweep K in {4, 6, 8} on our own train/dev data and keep the best on dev.

Data (ml/fetch_data.py; licences in docs/ML.md):
  train/dev   ASVspoof 2019 LA train (real + 6 TTS/VC systems), IndicSynth Hindi (synthetic), FLEURS Hindi train (real);
              every clip through one random phone channel (clean, G.711, or played over a speakerphone; ml/augment).
  held out    In-the-Wild (real-world celebrity deepfakes), ReplayDF (replayed through 20 loudspeaker/mic pairs),
              and our TTS: edge-tts en-IN/hi-IN voices on our 57 call scripts vs real FLEURS Hindi validation speech.
The threshold is set on dev so that 5% of real dev voices are flagged: in the app this signal can only raise the amber
card ("the voice may be computer-made"), never the red one, because over a speakerphone it is much weaker.

Outputs: models/voice_clone/voice.int8.onnx (+ voice.json), models/eval/voice_clone.json (EER and flags per set and channel,
scored with the shipped int8 model). Licence of the weights: CC BY-NC-SA 4.0 (AntiDeepfake), research and demo use.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "models" / "voice_clone"
EVAL = ROOT / "models" / "eval" / "voice_clone.json"
CKPT = ROOT / "models" / "s1_add_w2vlarge.pt"
LAYERS = (4, 6, 8)
TRAIN_S = 6.0
SEED = 11


# ------------------------------------------------------------------ data
def _clip(x: np.ndarray, seconds: float, rng: random.Random) -> np.ndarray:
    n = int(seconds * 16000)
    if len(x) <= n:
        return x
    s = rng.randrange(0, len(x) - n)
    return x[s : s + n]


def _channel(x: np.ndarray, ch: str, genuine: bool, seed: int) -> np.ndarray:
    from ml.augment.telephony import channel

    return x if ch == "clean" else channel(x.astype(np.float32), ch, seed=seed, genuine=genuine).astype(np.float32)


def train_pool(n_each: int, rng: random.Random) -> list[dict]:
    from ml.build_manifest import _decode, _rows

    out = []

    def take(source, limit, label, keep=lambda r: True, lang="en", name=None):
        k = 0
        for r in _rows(source, limit * 3, seed=SEED):
            if k >= limit or not keep(r):
                continue
            x = _decode(r["audio"])
            if x is None or len(x) < 16000:
                continue
            out.append({"x": _clip(x, TRAIN_S, rng), "label": label, "source": name or source, "lang": lang})
            k += 1

    take("asv19_train", n_each, 0, keep=lambda r: str(r.get("system_id")) == "-" or r.get("key") == 0)
    take("asv19_train", n_each, 1, keep=lambda r: not (str(r.get("system_id")) == "-" or r.get("key") == 0))
    take("indicsynth_hi", n_each, 1, lang="hi")
    # FLEURS train only: the spot-check kit and the held-out real voices come from FLEURS validation
    from ml import build_manifest

    files = [f for f in sorted((build_manifest.DS / "fleurs_hi").rglob("*.parquet")) if "train" in f.name]
    import pyarrow.parquet as pq

    k = 0
    for f in files:
        for b in pq.ParquetFile(f).iter_batches(batch_size=128):
            for r in b.to_pylist():
                if k >= n_each:
                    break
                x = _decode(r["audio"])
                if x is not None and len(x) >= 16000:
                    out.append({"x": _clip(x, TRAIN_S, rng), "label": 0, "source": "fleurs_hi", "lang": "hi"})
                    k += 1
    for i, r in enumerate(out):
        ch = rng.choice(["clean", "g711u", "ota+g711u"])
        r["x"] = _channel(r["x"], ch, genuine=r["label"] == 0, seed=i)
        r["channel"] = ch
        h = int(hashlib.sha1(f"{SEED}:{i}".encode()).hexdigest()[:8], 16) / 2**32
        r["split"] = "dev" if h < 0.15 else "train"
    return out


def held_out(n: int, rng: random.Random) -> list[dict]:
    """Test sets, each clip in its channels. Never used to pick anything."""
    from ml.build_manifest import _decode, _rows

    out = []
    k = 0
    for r in _rows("itw", n * 2, seed=SEED + 1):
        if k >= n:
            break
        x = _decode(r["audio"])
        if x is None or len(x) < 16000:
            continue
        x = _clip(x, 12.0, rng)
        lab = 0 if int(r["label"]) == 0 else 1
        for ch in ("clean", "g711u"):
            out.append({"x": _channel(x, ch, lab == 0, k), "label": lab, "set": "In-the-Wild", "channel": ch})
        k += 1
    # ReplayDF: already played through a loudspeaker into a mic; through the phone line on top
    import csv

    import soundfile as sf

    from engine.audio.codec import resample
    from ml.build_manifest import DS

    metas = sorted((DS / "replaydf" / "wav").glob("*/meta.csv"))
    rows = []
    for m in metas:
        with open(m, encoding="utf-8", newline="") as f:
            rows += [r for r in csv.DictReader(f, delimiter="|") if r["language"] == "en" and (DS / "replaydf" / r["recorded_file"]).exists()]
    rng.shuffle(rows)
    for i, r in enumerate(rows[: n // 2]):
        x, sr = sf.read(DS / "replaydf" / r["recorded_file"], dtype="float32", always_2d=True)
        x = _clip(resample(x.mean(axis=1), sr, 16000), 12.0, rng)
        lab = 0 if r["label"] == "bona-fide" else 1
        out.append({"x": _channel(x, "g711u", lab == 0, i), "label": lab, "set": "ReplayDF (speaker→mic)", "channel": "g711u"})
    # our TTS calls (AI) vs FLEURS Hindi validation (real)
    from ml.eval import asr_bakeoff

    calls = asr_bakeoff.calls()
    fake = [asr_bakeoff.audio_for(r, i) for i, r in enumerate(calls)]
    import pyarrow.parquet as pq

    real = []
    for f in sorted((DS / "fleurs_hi").rglob("validation-*.parquet")):
        for b in pq.ParquetFile(f).iter_batches(batch_size=64):
            for r in b.to_pylist():
                x = _decode(r["audio"])
                if x is not None and len(x) >= 32000 and len(real) < len(fake):
                    real.append(x)
    for lab, xs in ((1, fake), (0, real)):
        for i, x in enumerate(xs):
            x = _clip(x, 20.0, rng)
            for ch in ("clean", "g711u", "ota+g711u"):
                out.append({"x": _channel(x, ch, lab == 0, 1000 + i), "label": lab, "set": "Stock TTS (edge-tts) vs real Hindi", "channel": ch})
    return out


# ------------------------------------------------------------------ model
def load_backbone(max_layers: int):
    import torch

    from engine.signals.antideepfake_model import AntiDeepfakeModel, backbone_config

    ck = torch.load(CKPT, map_location="cpu", weights_only=False)
    cfg = backbone_config(ck["config"])
    cfg.num_hidden_layers = max_layers
    m = AntiDeepfakeModel(cfg)
    sd = {k: v for k, v in ck["state_dict"].items() if not any(f"encoder.layers.{i}." in k for i in range(max_layers, 64))}
    missing, unexpected = m.load_state_dict(sd, strict=False)
    assert not [k for k in missing if not k.startswith("head.")], missing
    return m.eval()


def layer_outputs(ssl, x, upto: int) -> list:
    """Each transformer layer's output, 1..upto, as training and the exported model see them. W2V-Large is pre-norm
    ("stable layer norm"): the encoder's final layer norm belongs after its last layer, so a cut network skips it."""
    feats = ssl.feature_extractor(x).transpose(1, 2)
    h, _ = ssl.feature_projection(feats)
    enc = ssl.encoder
    h = h + enc.pos_conv_embed(h)
    outs = []
    for layer in enc.layers[:upto]:
        h = layer(h)[0]
        outs.append(h)
    return outs


def embed(model, clips: list[np.ndarray], layers=LAYERS, device: str = "cpu") -> dict[int, np.ndarray]:
    """Mean-pooled hidden state after each layer in [layers], per clip."""
    import torch
    import torch.nn.functional as F

    model = model.to(device)
    out = {k: [] for k in layers}
    with torch.inference_mode():
        for x in clips:
            t = torch.from_numpy(np.asarray(x, dtype=np.float32))[None].to(device)
            t = F.layer_norm(t, t.shape[-1:])
            hs = layer_outputs(model.ssl, t, max(layers))
            for k in layers:
                out[k].append(hs[k - 1].mean(dim=1)[0].float().cpu().numpy())
    return {k: np.stack(v) for k, v in out.items()}


def fit_head(Xtr, ytr, Xdv, ydv):
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import log_loss

    mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-6
    best = None
    for C in (0.01, 0.1, 1.0):
        lr = LogisticRegression(C=C, max_iter=3000, class_weight="balanced").fit((Xtr - mu) / sd, ytr)
        p = lr.predict_proba((Xdv - mu) / sd)[:, 1]
        loss = log_loss(ydv, p, labels=[0, 1])
        if best is None or loss < best[0]:
            best = (loss, C, lr, p)
    return best[2], mu, sd, best[3], best[1]


class Exported:
    """waveform → layer norm → CNN → first K layers → mean → (x - mu) / sd → linear → sigmoid: P(AI voice)."""

    @staticmethod
    def module(model, k: int, lr, mu, sd):
        import torch
        import torch.nn as nn

        class M(nn.Module):
            def __init__(self):
                super().__init__()
                self.ssl = model.ssl
                self.ssl.encoder.layers = self.ssl.encoder.layers[:k]
                self.register_buffer("mu", torch.tensor(mu, dtype=torch.float32))
                self.register_buffer("sd", torch.tensor(sd, dtype=torch.float32))
                self.lin = nn.Linear(len(mu), 1)
                self.lin.weight.data = torch.tensor(lr.coef_, dtype=torch.float32)
                self.lin.bias.data = torch.tensor(lr.intercept_, dtype=torch.float32)

            def forward(self, audio):
                # the whole-clip layer norm, written out so the length can vary in ONNX
                mean = audio.mean(dim=-1, keepdim=True)
                var = ((audio - mean) ** 2).mean(dim=-1, keepdim=True)
                x = (audio - mean) / torch.sqrt(var + 1e-5)
                h = layer_outputs(self.ssl, x, k)[-1]
                z = (h.mean(dim=1) - self.mu) / self.sd
                return torch.sigmoid(self.lin(z))

        return M().eval()


def export(model, k: int, lr, mu, sd, probe: list[np.ndarray]) -> tuple[Path, float]:
    import onnxruntime as ort
    import torch
    from onnxruntime.quantization import QuantType, quantize_dynamic

    OUT.mkdir(parents=True, exist_ok=True)
    m = Exported.module(model, k, lr, mu, sd)
    fp32 = OUT / "voice.fp32.onnx"
    x = torch.from_numpy(probe[0][None].astype(np.float32))
    torch.onnx.export(m, (x,), str(fp32), input_names=["audio"], output_names=["p_ai"], dynamic_axes={"audio": {1: "samples"}}, opset_version=17, dynamo=False)
    q = OUT / "voice.int8.onnx"
    quantize_dynamic(str(fp32), str(q), weight_type=QuantType.QInt8)
    s = ort.InferenceSession(str(q), providers=["CPUExecutionProvider"])
    with torch.inference_mode():
        ref = [float(m(torch.from_numpy(p[None].astype(np.float32)))[0, 0]) for p in probe]
    got = [float(s.run(None, {"audio": p[None].astype(np.float32)})[0].reshape(-1)[0]) for p in probe]
    gap = float(np.max(np.abs(np.array(ref) - np.array(got))))
    fp32.unlink()
    return q, gap


def score_onnx(path: Path, clips: list[np.ndarray]) -> np.ndarray:
    import onnxruntime as ort

    s = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    return np.array([float(s.run(None, {"audio": c[None].astype(np.float32)})[0].reshape(-1)[0]) for c in clips])


def main() -> int:
    from ml.eval.metrics import eer, wilson

    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    rng = random.Random(SEED)
    import torch

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    n_each = 200 if a.quick else 900
    print("collecting train/dev …", flush=True)
    pool = train_pool(n_each, rng)
    model = load_backbone(max(LAYERS))
    print(f"embedding {len(pool)} train/dev clips on {device} …", flush=True)
    E = embed(model, [r["x"] for r in pool], device=device)
    y = np.array([r["label"] for r in pool])
    tr = np.array([r["split"] == "train" for r in pool])
    sweep = {}
    for k in LAYERS:
        lr, mu, sd, pdev, C = fit_head(E[k][tr], y[tr], E[k][~tr], y[~tr])
        e, _ = eer(pdev[y[~tr] == 0], pdev[y[~tr] == 1])
        sweep[k] = {"dev_eer": round(e, 4), "C": C, "head": (lr, mu, sd), "pdev": pdev}
        print(f"K={k}: dev EER {100 * e:.1f}%", flush=True)
    k = min(LAYERS, key=lambda kk: (sweep[kk]["dev_eer"], kk))
    lr, mu, sd = sweep[k]["head"]
    pdev = sweep[k]["pdev"]
    print(f"exporting K={k} …", flush=True)
    model = load_backbone(k)
    q, gap = export(model, k, lr, mu, sd, [r["x"] for r in pool[:8]])
    # the threshold on dev, with the shipped int8 model: 5% of real dev voices flagged
    dev = [r for r in pool if r["split"] == "dev"]
    pq_dev = score_onnx(q, [r["x"] for r in dev])
    yd = np.array([r["label"] for r in dev])
    thr = float(np.quantile(pq_dev[yd == 0], 0.95))
    meta = {"layers": k, "threshold": round(thr, 4), "seconds": 20, "dev_eer_fp32": {str(kk): sweep[kk]["dev_eer"] for kk in LAYERS}, "int8_vs_fp32_max_gap": round(gap, 4),
            "size_mb": round(q.stat().st_size / 1e6, 1), "trained_on": sorted({r["source"] for r in pool}), "train_clips": int(tr.sum()), "dev_clips": int((~tr).sum()), "seed": SEED,
            "licence": "CC BY-NC-SA 4.0 (derived from nii-yamagishilab/wav2vec-large-anti-deepfake)"}  # fmt: skip
    (OUT / "voice.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print("scoring held-out sets with the int8 model …", flush=True)
    test = held_out(150 if a.quick else 500, rng)
    p = score_onnx(q, [r["x"] for r in test])
    res = {"model": meta, "sets": {}}
    for key in sorted({(r["set"], r["channel"]) for r in test}):
        idx = [i for i, r in enumerate(test) if (r["set"], r["channel"]) == key]
        yy = np.array([test[i]["label"] for i in idx])
        pp = p[idx]
        e, _ = eer(pp[yy == 0], pp[yy == 1]) if (yy == 0).any() and (yy == 1).any() else (float("nan"), 0)
        fr = int(((pp >= thr) & (yy == 0)).sum())
        fk = int(((pp >= thr) & (yy == 1)).sum())
        nr, nf = int((yy == 0).sum()), int((yy == 1).sum())
        res["sets"][f"{key[0]} | {key[1]}"] = {
            "eer": round(e, 4),
            "real_flagged": [fr, nr, [round(v, 3) for v in wilson(fr, nr)]],
            "fakes_caught": [fk, nf, [round(v, 3) for v in wilson(fk, nf)]],
        }
    lines = [
        f"First {k} layers of AntiDeepfake W2V-Large + logistic head, ONNX int8 ({meta['size_mb']} MB), threshold {thr:.2f} (5% of real dev voices flagged). Dev EER by depth: "
        + ", ".join(f"K={kk}: {100 * sweep[kk]['dev_eer']:.1f}%" for kk in LAYERS)
        + f". int8 vs fp32 max gap {gap:.3f}.",
        "",
        "| Held-out set | Channel | EER | Real voices flagged | AI voices caught |",
        "|---|---|---|---|---|",
    ]
    for name, d in res["sets"].items():
        s, ch = name.split(" | ")
        rf, fc = d["real_flagged"], d["fakes_caught"]
        lines.append(
            f"| {s} | {ch} | {100 * d['eer']:.1f}% | {100 * rf[0] / max(1, rf[1]):.0f}% ({rf[0]}/{rf[1]}) | {100 * fc[0] / max(1, fc[1]):.0f}% ({fc[0]}/{fc[1]}) |"
        )
    res["markdown"] = "\n".join(lines)
    res["seconds"] = round(time.time() - t0)
    EVAL.write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")
    print(res["markdown"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
