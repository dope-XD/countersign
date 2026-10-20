"""Fine-tune an S1 model for phone audio and Indian languages, on one 8 GB laptop GPU.

    python -m ml.train_s1 --init models/s1_sls_hf.pt --out models/s1_sls_phone.pt --steps 4000
    python -m ml.train_s1 --init models/s1_add_mms300m.pt --out models/s1_add_mms300m_phone.pt         --version add-mms-300m-phone --lr 2e-7 --head-lr 2e-6 --steps 2000

The architecture (XLS-R + SLS or AntiDeepfake) comes from the --init checkpoint.

- Every training clip goes through a random telephony chain (G.711/AMR-NB/GSM/iLBC/Opus,
  noise, packet loss, band-limit) in DataLoader workers.
- Balanced batches: half bona fide, half spoof, mixed across sources.
- bf16 autocast, frozen CNN feature encoder, gradient checkpointing, gradient accumulation.
- Dev EER on a fixed phone-channel copy of the dev split. The kept checkpoint is the one with
  the best mean of the overall dev EER and the Hindi-only dev EER (FLEURS real vs IndicSynth
  fake), so a step that helps English but starts calling Hindi speech fake is not kept.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader

from ml.eval.metrics import eer
from ml.s1_data import BalancedSampler, DevSet, TrainSet, read

INDIC = ("fleurs_hi", "indicsynth", "kathbath_hi", "mlaad")  # manifest `source` values in Indian languages


@torch.no_grad()
def evaluate(model, loader, device, sources: list[str]) -> dict:
    """Dev EER overall and on the Indian-language rows. Scores are spoof log-odds (both
    architectures put spoof in column 0), so no softmax is needed."""
    model.eval()
    scores, labels = [], []
    for x, y in loader:
        with torch.autocast("cuda", dtype=torch.bfloat16, enabled=device == "cuda"):
            out = model(x.to(device)).float()
        scores += (out[:, 0] - out[:, 1]).cpu().tolist()
        labels += y.tolist()
    model.train()
    s, is_bona = np.array(scores), np.array(labels) == 1
    indic = np.array([src in INDIC for src in sources])
    e_all, _ = eer(s[is_bona], s[~is_bona])
    res = {"dev_eer": e_all, "indic_eer": None, "select": e_all}
    if (indic & is_bona).any() and (indic & ~is_bona).any():
        e_in, _ = eer(s[indic & is_bona], s[indic & ~is_bona])
        res |= {"indic_eer": e_in, "select": (e_all + e_in) / 2}
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", default="models/s1_sls_hf.pt")
    ap.add_argument("--out", default="models/s1_sls_phone.pt")
    ap.add_argument("--train", default="data/manifests/train.csv")
    ap.add_argument("--dev", default="data/manifests/dev.csv")
    ap.add_argument("--steps", type=int, default=4000)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--accum", type=int, default=4)
    ap.add_argument("--lr", type=float, default=2e-6)
    ap.add_argument("--head-lr", type=float, default=2e-5)
    ap.add_argument("--eval-every", type=int, default=250)
    ap.add_argument("--dev-limit", type=int, default=0, help="0 = the whole dev split")
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--version", default="xlsr-sls-phone-indic")
    a = ap.parse_args()

    from engine.signals.s1_synth import build_model  # heavy; keep out of DataLoader workers

    device = "cuda" if torch.cuda.is_available() else "cpu"
    torch.manual_seed(0)
    ck = torch.load(a.init, map_location="cpu", weights_only=False)
    model, arch = build_model(ck)
    model.load_state_dict(ck.get("state_dict", ck))
    model.ssl.freeze_feature_encoder()
    model.set_checkpointing(True)
    model.to(device).train()
    keep = {k: ck[k] for k in ("arch", "config") if isinstance(ck, dict) and k in ck}  # so the engine can rebuild it

    train_rows = read(a.train)
    dev_rows = read(a.dev)
    random.Random(0).shuffle(dev_rows)
    if a.dev_limit:
        dev_rows = dev_rows[: a.dev_limit]
    dev_sources = [r.get("source", "") for r in dev_rows]
    print(f"{arch}: train {len(train_rows)} rows, dev {len(dev_rows)} rows, device {device}")

    n_samples = a.steps * a.batch * a.accum
    train_dl = DataLoader(
        TrainSet(train_rows),
        batch_size=a.batch,
        sampler=BalancedSampler(train_rows, n_samples),
        num_workers=a.workers,
        persistent_workers=a.workers > 0,
        prefetch_factor=4 if a.workers else None,
        drop_last=True,
    )
    dev_dl = DataLoader(DevSet(dev_rows), batch_size=16, num_workers=2)

    backbone = [p for n, p in model.named_parameters() if n.startswith("ssl.") and p.requires_grad]
    head = [p for n, p in model.named_parameters() if not n.startswith("ssl.")]
    opt = torch.optim.AdamW([{"params": backbone, "lr": a.lr}, {"params": head, "lr": a.head_lr}], weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / 200) * 0.5 * (1 + math.cos(math.pi * min(1.0, s / a.steps))))
    base = evaluate(model, dev_dl, device, dev_sources)
    print(f"step 0 {fmt(base)}")
    best = base["select"]
    log = [{"step": 0, **base}]
    step, micro, t0, running = 0, 0, time.time(), 0.0
    opt.zero_grad(set_to_none=True)
    for x, y in train_dl:
        with torch.autocast("cuda", dtype=torch.bfloat16, enabled=device == "cuda"):
            out = model(x.to(device, non_blocking=True))
        # SLS returns log-probabilities, AntiDeepfake logits; cross-entropy is right for both
        # (log_softmax of log-probabilities is a no-op)
        loss = F.cross_entropy(out.float(), y.to(device)) / a.accum
        loss.backward()
        running += loss.item()
        micro += 1
        if micro % a.accum:
            continue
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        sched.step()
        opt.zero_grad(set_to_none=True)
        step += 1
        if step % 25 == 0:
            mem = torch.cuda.max_memory_allocated() / 2**30 if device == "cuda" else 0
            print(f"step {step} loss {running / 25:.4f} {(time.time() - t0) / step:.2f}s/step peak {mem:.1f} GB", flush=True)
            running = 0.0
        if step % a.eval_every == 0 or step == a.steps:
            res = evaluate(model, dev_dl, device, dev_sources)
            log.append({"step": step, **res})
            print(f"step {step} {fmt(res)} (best {best:.4f})", flush=True)
            if res["select"] < best:
                best = res["select"]
                torch.save({**keep, "state_dict": model.state_dict(), "version": a.version, **res, "step": step, "init": a.init}, a.out)
                print("  saved", a.out, flush=True)
        if step >= a.steps:
            break
    Path(a.out).with_suffix(".log.json").write_text(json.dumps({"baseline": base, "best_select": best, "log": log}, indent=2))
    print(f"done. baseline {base['select']:.4f} -> best {best:.4f}")


def fmt(r: dict) -> str:
    indic = f"{r['indic_eer']:.4f}" if r["indic_eer"] is not None else "n/a"
    return f"dev EER {r['dev_eer']:.4f}, Hindi {indic}, select {r['select']:.4f}"


if __name__ == "__main__":
    main()
