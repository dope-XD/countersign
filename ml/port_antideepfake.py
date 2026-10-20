"""Convert a released AntiDeepfake checkpoint (fairseq names) into AntiDeepfakeModel.

    python -m ml.port_antideepfake nii-yamagishilab/mms-300m-anti-deepfake models/s1_add_mms300m.pt
    python -m ml.port_antideepfake nii-yamagishilab/xls-r-1b-anti-deepfake models/s1_add_xlsr1b.pt

The Hugging Face repo holds config.json (the backbone shape, in transformers terms) and
model.safetensors (the whole network under fairseq names: `m_ssl.model.*` + `proj_fc.*`).
The backbone tensors use the same fairseq layout as XLS-R + SLS, so the key mapping is
shared with ml/port_sls_checkpoint.py. Every tensor must map and every parameter must be
filled, or this fails. The config is stored in the output so the engine needs no download.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import torch
from huggingface_hub import hf_hub_download
from safetensors.torch import load_file

from engine.config import settings
from engine.signals.antideepfake_model import AntiDeepfakeModel, backbone_config
from ml.port_sls_checkpoint import map_key


def map_add_key(k: str, target_keys: set[str]) -> str | None:
    if k.startswith("proj_fc."):
        return "head." + k.split(".", 1)[1]
    k = re.sub(r"^m_ssl\.model\.", "ssl_model.model.", k)
    return map_key(k, target_keys)


def convert(repo: str, dst: str, version: str | None) -> None:
    cache = str(settings.models_dir / "hf")
    cfg = json.loads(Path(hf_hub_download(repo, "config.json", cache_dir=cache)).read_text(encoding="utf-8"))
    src = load_file(hf_hub_download(repo, "model.safetensors", cache_dir=cache))
    model = AntiDeepfakeModel(backbone_config(cfg))
    target = model.state_dict()
    tkeys = set(target)
    out, unmapped, dropped = {}, [], 0
    for k, v in src.items():
        nk = map_add_key(k, tkeys)
        if nk is None:
            dropped += 1
            continue
        if nk.startswith("UNMAPPED:") or nk not in tkeys:
            unmapped.append(k)
            continue
        if target[nk].shape != v.shape:
            if target[nk].numel() != v.numel():
                raise SystemExit(f"shape mismatch {k} {tuple(v.shape)} -> {nk} {tuple(target[nk].shape)}")
            v = v.reshape(target[nk].shape)
        out[nk] = v.float() if v.is_floating_point() else v
    # pretraining-only parameter, never used without masking
    if "ssl.masked_spec_embed" in tkeys and "ssl.masked_spec_embed" not in out:
        out["ssl.masked_spec_embed"] = target["ssl.masked_spec_embed"]
    missing = [k for k in tkeys if k not in out]
    print(f"mapped {len(out)} tensors, dropped {dropped} pretraining-only, unmapped {len(unmapped)}, missing {len(missing)}")
    if unmapped:
        print("UNMAPPED:", unmapped[:20])
    if missing:
        print("MISSING:", missing[:20])
    if unmapped or missing:
        sys.exit(1)
    model.load_state_dict(out, strict=True)
    version = version or "add-" + repo.split("/")[-1].removesuffix("-anti-deepfake")
    torch.save({"arch": "antideepfake", "config": cfg, "state_dict": model.state_dict(), "version": version, "source": repo}, dst)
    print("saved", dst, "version", version)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("dst")
    ap.add_argument("--version", default=None)
    a = ap.parse_args()
    convert(a.repo, a.dst, a.version)
