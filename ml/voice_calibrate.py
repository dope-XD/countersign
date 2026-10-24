"""Set the voice-clone threshold on a calibration set that is neither training nor test data.

    python -m ml.voice_calibrate        # after ml.voice_clone; updates voice.json and the tables in voice_clone.json

Why: the voice model ranks voices well on held-out data (EER 10–25%) but its scores sit at different levels in
different domains, so a cut-off picked on in-domain dev data (or a fixed 0.9) misfires on Indian phone audio.
Calibration set: a TTS generator used nowhere else (Google's gTTS, Hindi and Indian English) against real FLEURS
Hindi *train* speakers the model never saw (indices after the ones ml.voice_clone trains on), each through a G.711
line and the speakerphone path. The threshold is that set's equal-error point. The held-out tables are then recomputed
from the scores ml.voice_clone saved, so the test sets are never used to choose anything.
"""

from __future__ import annotations

import io
import json
import random
from pathlib import Path

import numpy as np

from ml.voice_clone import EVAL, OUT, _channel, _clip, score_onnx

ROOT = Path(__file__).resolve().parent.parent
N = 60
SEED = 5


def calibration_set() -> list[dict]:
    import pyarrow.parquet as pq
    from gtts import gTTS

    from engine.audio.codec import resample
    from ml.build_manifest import DS, _decode

    rng = random.Random(SEED)
    real, sentences = [], []
    files = [f for f in sorted((DS / "fleurs_hi").rglob("*.parquet")) if "train" in f.name]
    rows = [r for f in files for b in pq.ParquetFile(f).iter_batches(batch_size=128) for r in b.to_pylist()]
    for r in rows[-400:]:  # the tail of FLEURS train: ml.voice_clone samples from the start
        x = _decode(r["audio"])
        if x is not None and len(x) >= 48000 and len(real) < N:
            real.append(_clip(x, 15.0, rng))
            sentences.append(r.get("transcription") or "")
    import soundfile as sf

    fake = []
    for i, s in enumerate(sentences[:N]):
        buf = io.BytesIO()
        gTTS(s or "नमस्ते", lang="hi", tld=["co.in", "com"][i % 2]).write_to_fp(buf)
        buf.seek(0)
        y, sr = sf.read(buf, dtype="float32", always_2d=False)
        y = y.mean(axis=1) if y.ndim > 1 else y
        fake.append(resample(y, sr, 16000).astype(np.float32))
    out = []
    for lab, xs in ((0, real), (1, fake)):
        for i, x in enumerate(xs):
            for ch in ("g711u", "ota+g711u"):
                out.append({"x": _channel(x, ch, lab == 0, 5000 + i), "label": lab, "channel": ch})
    return out


def main() -> int:
    from ml.eval.metrics import eer, wilson

    cal = calibration_set()
    q = OUT / "voice.int8.onnx"
    p = score_onnx(q, [r["x"] for r in cal])
    y = np.array([r["label"] for r in cal])
    e, thr = eer(p[y == 0], p[y == 1])
    meta = json.loads((OUT / "voice.json").read_text(encoding="utf-8"))
    meta["threshold"] = round(float(thr), 4)
    meta["calibration"] = {
        "set": "gTTS (hi, co.in/com) vs FLEURS hi train tail, G.711 + speakerphone",
        "clips": len(cal),
        "eer": round(e, 4),
        "rule": "equal-error point",
    }
    (OUT / "voice.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    res = json.loads(EVAL.read_text(encoding="utf-8"))
    res["model"] = meta
    lines = [
        f"First {meta['layers']} layers of AntiDeepfake W2V-Large + logistic head, ONNX int8 ({meta['size_mb']} MB). A voice is flagged at P(AI) ≥ {thr:.3f}, the"
        f" equal-error point on a calibration set used nowhere else (gTTS vs unseen FLEURS speakers; EER there {100 * e:.1f}%).",
        "",
        "| Held-out set | Channel | EER | Real voices flagged | AI voices caught |",
        "|---|---|---|---|---|",
    ]
    for name, d in res["sets"].items():
        r_, a_ = np.array(d["scores_real"]), np.array(d["scores_ai"])
        fr, fk = int((r_ >= thr).sum()), int((a_ >= thr).sum())
        d["real_flagged"] = [fr, len(r_), [round(v, 3) for v in wilson(fr, len(r_))]]
        d["fakes_caught"] = [fk, len(a_), [round(v, 3) for v in wilson(fk, len(a_))]]
        s, ch = name.split(" | ")
        lines.append(
            f"| {s} | {ch} | {100 * d['eer']:.1f}% | {100 * fr / max(1, len(r_)):.0f}% ({fr}/{len(r_)}) | {100 * fk / max(1, len(a_)):.0f}% ({fk}/{len(a_)}) |"
        )
    res["markdown"] = "\n".join(lines)
    EVAL.write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")
    print(res["markdown"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
