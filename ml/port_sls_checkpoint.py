"""Convert a fairseq-based XLS-R + SLS checkpoint into the HF-transformers SLSModel.

    python -m ml.port_sls_checkpoint models/src/sls_v1_epoch_2.pth models/s1_sls_hf.pt

The published checkpoints hold the whole fine-tuned network (backbone + head) under
fairseq names, usually prefixed with `module.` (DataParallel) and `ssl_model.model.`.
Every tensor must map, and every SLSModel parameter must be filled, or this fails.
"""

from __future__ import annotations

import argparse
import re
import sys

import torch

from engine.signals.sls_model import SLSModel

DROP = ("quantizer.", "project_q.", "final_proj.", "label_embs", "target_glu", "mask_emb")  # mask_emb: only used for pre-training masks


def map_key(k: str, target_keys: set[str]) -> str | None:
    k = re.sub(r"^module\.", "", k)
    if not k.startswith("ssl_model."):
        return k  # head: first_bn, fc0, fc1, fc3
    k = re.sub(r"^ssl_model\.model\.", "", k)
    if k.startswith(DROP):
        return None
    m = re.match(r"feature_extractor\.conv_layers\.(\d+)\.0\.(weight|bias)$", k)
    if m:
        return f"ssl.feature_extractor.conv_layers.{m[1]}.conv.{m[2]}"
    m = re.match(r"feature_extractor\.conv_layers\.(\d+)\.2\.1\.(weight|bias)$", k)
    if m:
        return f"ssl.feature_extractor.conv_layers.{m[1]}.layer_norm.{m[2]}"
    if k.startswith("layer_norm."):
        return "ssl.feature_projection." + k
    if k.startswith("post_extract_proj."):
        return "ssl.feature_projection.projection." + k.split(".", 1)[1]
    if k == "mask_emb":
        return "ssl.masked_spec_embed"
    m = re.match(r"encoder\.pos_conv\.0\.(weight_g|weight_v|bias)$", k)
    if m:
        base = "ssl.encoder.pos_conv_embed.conv."
        if m[1] == "bias":
            return base + "bias"
        old = base + m[1]
        if old in target_keys:
            return old
        return base + ("parametrizations.weight.original0" if m[1] == "weight_g" else "parametrizations.weight.original1")
    if k.startswith("encoder.layer_norm."):
        return "ssl." + k
    m = re.match(r"encoder\.layers\.(\d+)\.(.+)$", k)
    if m:
        i, rest = m[1], m[2]
        rest = (
            rest.replace("self_attn_layer_norm", "layer_norm")
            .replace("self_attn.", "attention.")
            .replace("fc1.", "feed_forward.intermediate_dense.")
            .replace("fc2.", "feed_forward.output_dense.")
        )
        return f"ssl.encoder.layers.{i}.{rest}"
    return "UNMAPPED:" + k


def convert(src: str, dst: str, version: str) -> None:
    ckpt = torch.load(src, map_location="cpu", weights_only=False)
    if isinstance(ckpt, dict) and "state_dict" in ckpt:
        ckpt = ckpt["state_dict"]
    if isinstance(ckpt, dict) and "model" in ckpt and isinstance(ckpt["model"], dict):
        ckpt = ckpt["model"]
    model = SLSModel()
    target = model.state_dict()
    tkeys = set(target)
    out, unmapped, dropped = {}, [], 0
    for k, v in ckpt.items():
        nk = map_key(k, tkeys)
        if nk is None:
            dropped += 1
            continue
        if nk.startswith("UNMAPPED:") or nk not in tkeys:
            unmapped.append(k)
            continue
        if target[nk].shape != v.shape:
            # weight-norm g has shape (1,1,K) in fairseq and the same in HF; anything else is a bug
            if target[nk].numel() == v.numel():
                v = v.reshape(target[nk].shape)
            else:
                raise SystemExit(f"shape mismatch {k} {tuple(v.shape)} -> {nk} {tuple(target[nk].shape)}")
        out[nk] = v.float() if v.is_floating_point() else v
    missing = [k for k in tkeys if k not in out and not k.endswith("num_batches_tracked")]
    print(f"mapped {len(out)} tensors, dropped {dropped} pretraining-only, unmapped {len(unmapped)}, missing {len(missing)}")
    if unmapped:
        print("UNMAPPED:", unmapped[:20])
    if missing:
        print("MISSING:", missing[:20])
    if unmapped or missing:
        sys.exit(1)
    for k in tkeys:
        if k.endswith("num_batches_tracked") and k not in out:
            out[k] = target[k]
    model.load_state_dict(out, strict=True)
    torch.save({"state_dict": model.state_dict(), "version": version, "source": src}, dst)
    print("saved", dst)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--version", default="xlsr-sls-asvspoof19-v1")
    a = ap.parse_args()
    convert(a.src, a.dst, a.version)
