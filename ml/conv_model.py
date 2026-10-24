"""Fine-tune the conversation model: multilingual-e5-small (118M, MIT) + one logistic output, on ml.conv_data.

    python -m ml.conv_model train --data data/conv --out models/conv_model     # on a GPU (the RTX laptop)
    python -m ml.conv_model export --model models/conv_model                   # ONNX fp32 (shipped), parity-checked

The model reads the call so far (the last ~320 tokens, made the way the phone makes it) and gives P(the caller has
already made a scam move). It replaces keyword cues: it was trained on whole conversations where genuine bank calls
use the same words as scams, so it has to learn what is being asked and how, not which words appear.
Checkpoints are chosen on dev only (ICFD validation + our dev splits); test sets are never read here.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd

BASE = "intfloat/multilingual-e5-small"
MAX_LEN = 320  # covers 99% of the 1,200-character windows; longer ones lose their oldest words (left truncation)
PREFIX = "query: "


def tokenizer(path: str):
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(path)
    tok.truncation_side = "left"  # the newest turn matters most: never cut it
    return tok


def build(base: str):
    import torch
    import torch.nn as nn
    from transformers import AutoModel

    class ConvModel(nn.Module):
        def __init__(self):
            super().__init__()
            self.enc = AutoModel.from_pretrained(base)
            self.head = nn.Linear(self.enc.config.hidden_size, 1)

        def forward(self, input_ids, attention_mask):
            h = self.enc(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state
            m = attention_mask.unsqueeze(-1).to(h.dtype)
            pooled = (h * m).sum(1) / m.sum(1).clamp(min=1.0)  # mean pooling, as e5 is trained
            return torch.sigmoid(self.head(pooled)).squeeze(-1)

    return ConvModel()


def auc(y: np.ndarray, p: np.ndarray) -> float:
    from sklearn.metrics import roc_auc_score

    return float(roc_auc_score(y, p)) if len(set(y.tolist())) > 1 else float("nan")


def train(a) -> None:
    import torch
    from transformers import get_linear_schedule_with_warmup

    torch.manual_seed(7)
    dev_ = torch.device("cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu")
    tok = tokenizer(a.base)
    tr = pd.read_parquet(Path(a.data) / "train.parquet")
    dv = pd.read_parquet(Path(a.data) / "dev.parquet")
    if a.max_rows and len(tr) > a.max_rows:
        tr = tr.sample(n=a.max_rows, random_state=7)
    if a.ours_weight > 1:
        # our sets are ~1.5% of rows but hold what ICFD lacks (Hindi folded to Latin, talk about scams, SMS): repeat them
        ours = tr[~tr["source"].str.startswith("icfd")]
        tr = pd.concat([tr] + [ours] * (a.ours_weight - 1), ignore_index=True)
    dv = dv.groupby("source", group_keys=False).apply(lambda g: g.sample(n=min(len(g), a.dev_rows // 3), random_state=7))
    model = build(a.base).to(dev_)
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=0.01)
    steps = math.ceil(len(tr) / a.bs) * a.epochs
    sched = get_linear_schedule_with_warmup(opt, int(0.05 * steps), steps)
    scaler = torch.amp.GradScaler(enabled=dev_.type == "cuda")
    pos = float(tr["label"].mean())
    w_pos = (1 - pos) / max(pos, 1e-3)  # balance the classes in the loss
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    log = []

    def batches(df: pd.DataFrame, bs: int):
        for i in range(0, len(df), bs):
            b = df.iloc[i : i + bs]
            enc = tok([PREFIX + t for t in b["text"]], max_length=MAX_LEN, truncation=True, padding=True, return_tensors="pt")
            yield enc["input_ids"].to(dev_), enc["attention_mask"].to(dev_), torch.tensor(b["label"].values, dtype=torch.float32, device=dev_)

    def evaluate() -> dict:
        model.eval()
        ps = []
        with torch.no_grad(), torch.autocast(dev_.type, enabled=dev_.type == "cuda"):
            for ids, am, _ in batches(dv, 128):
                ps.append(model(ids, am).float().cpu().numpy())
        model.train()
        p = np.concatenate(ps)
        y = dv["label"].values
        res = {"auc": auc(y, p)}
        for s, g in dv.assign(p=p).groupby("source"):
            res[f"auc_{s}"] = auc(g["label"].values, g["p"].values)
        return res

    best, step, t0 = -1.0, 0, time.time()
    model.train()
    for ep in range(a.epochs):
        tr = tr.sample(frac=1.0, random_state=ep)
        for ids, am, y in batches(tr, a.bs):
            with torch.autocast(dev_.type, enabled=dev_.type == "cuda"):
                p = model(ids, am).float().clamp(1e-6, 1 - 1e-6)
            w = torch.where(y > 0.5, torch.full_like(y, w_pos), torch.ones_like(y))
            loss = (-(y * torch.log(p) + (1 - y) * torch.log(1 - p)) * w).mean()
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(opt)
            scaler.update()
            sched.step()
            step += 1
            if step % 100 == 0:
                print(f"step {step}/{steps} loss {loss.item():.4f} {time.time() - t0:.0f}s", flush=True)
            if step % a.eval_every == 0 or step == steps:
                r = evaluate()
                r |= {"step": step, "seconds": round(time.time() - t0)}
                log.append(r)
                print(json.dumps(r), flush=True)
                score = np.nanmean([v for k, v in r.items() if k.startswith("auc_")])
                if score > best:
                    best = score
                    torch.save(model.state_dict(), out / "model.pt")
                    tok.save_pretrained(out)
                    (out / "train.json").write_text(
                        json.dumps(
                            {
                                "best_step": step,
                                "best_mean_source_auc": best,
                                "base": a.base,
                                "max_len": MAX_LEN,
                                "prefix": PREFIX,
                                "train_rows": len(tr),
                                "pos_rate": pos,
                                "log": log,
                            },
                            indent=2,
                        )
                    )
    print("done", best, flush=True)


def export(a) -> None:
    """ONNX fp32 (what the phone runs) checked against PyTorch, and an int8 variant measured for the record.

    int8 is not shipped: even per-channel, it moved p by up to ~0.2 on dev texts and flipped decisions near the
    thresholds, which are set on full-precision scores. fp32 is 470 MB and still fits the pack budget."""
    import onnxruntime as ort
    import torch
    from onnxruntime.quantization import QuantType, quantize_dynamic

    d = Path(a.model)
    meta = json.loads((d / "train.json").read_text())
    model = build(a.base)
    model.load_state_dict(torch.load(d / "model.pt", map_location="cpu"))
    model.eval()
    tok = tokenizer(str(d))
    texts = pd.read_parquet(Path(a.data) / "dev.parquet").sample(n=200, random_state=1)["text"].tolist()
    enc = tok([PREFIX + t for t in texts[:2]], max_length=MAX_LEN, truncation=True, padding=True, return_tensors="pt")
    fp32 = d / "conv.fp32.onnx"
    torch.onnx.export(
        model, (enc["input_ids"], enc["attention_mask"]), str(fp32), input_names=["input_ids", "attention_mask"], output_names=["p_scam"],
        dynamic_axes={"input_ids": {0: "b", 1: "n"}, "attention_mask": {0: "b", 1: "n"}, "p_scam": {0: "b"}}, opset_version=17, dynamo=False,
    )  # fmt: skip
    q = d / "conv.int8.onnx"
    quantize_dynamic(str(fp32), str(q), weight_type=QuantType.QInt8, op_types_to_quantize=["MatMul", "Gemm"], per_channel=True)
    sessions = {k: ort.InferenceSession(str(f), providers=["CPUExecutionProvider"]) for k, f in (("fp32", fp32), ("int8", q))}
    gaps: dict[str, list[float]] = {"fp32": [], "int8": []}
    for t in texts:
        e = tok([PREFIX + t], max_length=MAX_LEN, truncation=True, return_tensors="pt")
        with torch.no_grad():
            ref = float(model(e["input_ids"], e["attention_mask"])[0])
        for k, s in sessions.items():
            got = float(s.run(None, {"input_ids": e["input_ids"].numpy(), "attention_mask": e["attention_mask"].numpy()})[0][0])
            gaps[k].append(abs(ref - got))
    meta |= {
        "onnx_fp32_max_gap": round(max(gaps["fp32"]), 5),
        "int8_per_channel_max_gap": round(max(gaps["int8"]), 4),
        "int8_per_channel_mean_gap": round(float(np.mean(gaps["int8"])), 4),
        "shipped": "conv.fp32.onnx",
        "fp32_mb": round(fp32.stat().st_size / 1e6, 1),
    }
    (d / "train.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps({k: meta[k] for k in ("best_step", "best_mean_source_auc", "onnx_fp32_max_gap", "int8_per_channel_max_gap", "fp32_mb")}))
    assert max(gaps["fp32"]) < 1e-3, "ONNX fp32 differs from PyTorch"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["train", "export"])
    ap.add_argument("--data", default="data/conv")
    ap.add_argument("--out", default="models/conv_model")
    ap.add_argument("--model", default="models/conv_model")
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--bs", type=int, default=48)
    ap.add_argument("--lr", type=float, default=3e-5)
    ap.add_argument("--max-rows", type=int, default=240_000)
    ap.add_argument("--dev-rows", type=int, default=9_000)
    ap.add_argument("--eval-every", type=int, default=1000)
    ap.add_argument("--ours-weight", type=int, default=8, help="repeat our (non-ICFD) training rows this many times")
    a = ap.parse_args()
    train(a) if a.cmd == "train" else export(a)


if __name__ == "__main__":
    main()
