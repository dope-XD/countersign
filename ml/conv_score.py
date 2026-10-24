"""Score parquet files of calls-so-far with the trained conversation model (GPU if there is one).

    python -m ml.conv_score --model models/conv_model data/conv/dev.parquet data/conv/test_icfd.parquet ...

Writes <name>.scored.parquet next to each input with one more column, `p`. Used for setting the call thresholds (dev
only) and for the measurements in docs/RESULTS.md (test files); the phone runs the same model as int8 ONNX.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from ml.conv_model import BASE, MAX_LEN, PREFIX, build, tokenizer


def main() -> None:
    import torch

    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--model", default="models/conv_model")
    ap.add_argument("--bs", type=int, default=256)
    a = ap.parse_args()
    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tok = tokenizer(a.model)
    model = build(BASE)
    model.load_state_dict(torch.load(Path(a.model) / "model.pt", map_location="cpu"))
    model.to(dev).eval()
    for f in a.files:
        df = pd.read_parquet(f)
        order = np.argsort(df["text"].str.len().values)  # similar lengths together: less padding
        p = np.zeros(len(df), dtype=np.float32)
        with torch.no_grad(), torch.autocast(dev.type, enabled=dev.type == "cuda"):
            for i in range(0, len(df), a.bs):
                idx = order[i : i + a.bs]
                enc = tok([PREFIX + t for t in df["text"].values[idx]], max_length=MAX_LEN, truncation=True, padding=True, return_tensors="pt")
                p[idx] = model(enc["input_ids"].to(dev), enc["attention_mask"].to(dev)).float().cpu().numpy()
        out = Path(f).with_suffix(".scored.parquet")
        df.assign(p=p).to_parquet(out)
        print(out, len(df), flush=True)


if __name__ == "__main__":
    main()
