"""Turn downloaded parquet shards into 16 kHz FLAC clips + CSV manifests.

    python -m ml.build_manifest
    python -m ml.build_manifest --replaydf     only data/manifests/replaydf.csv

Writes data/clips/<source>/*.flac and data/manifests/{train,dev,asv19_eval,itw}.csv.
Clips are cut to at most 6 s, which is all S1 ever sees (4 s windows).

Splits keep sources honest:
  train/dev : ASVspoof19 LA train, IndicSynth Hindi, FLEURS hi (bona fide), Kathbath / MLAAD if present
  eval only : ASVspoof19 LA eval, In-the-Wild, ReplayDF, and IndiaCall (never used here)
"""

from __future__ import annotations

import csv
import io
import json
import random
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import soundfile as sf
from tqdm import tqdm

from engine.audio.codec import resample
from ml.s1_data import read

ROOT = Path(__file__).resolve().parent.parent / "data"
DS = ROOT / "datasets"
CLIPS = ROOT / "clips"
MAN = ROOT / "manifests"
MAX_S = 6.0
FIELDS = ["path", "label", "speaker", "language", "generator", "source", "split"]


def _decode(audio) -> np.ndarray | None:
    if isinstance(audio, dict):
        b = audio.get("bytes")
        if b is None and audio.get("path") and Path(audio["path"]).exists():
            b = Path(audio["path"]).read_bytes()
    else:
        b = audio
    if not b:
        return None
    try:
        x, sr = sf.read(io.BytesIO(b), dtype="float32", always_2d=True)
    except Exception:
        return None
    x = x.mean(axis=1)
    if sr != 16000:
        x = resample(x, sr, 16000)
    return x[: int(MAX_S * 16000)]


def _rows(source: str, limit: int | None, seed: int = 0):
    """Yield (row dict without audio, audio) from every parquet shard of a source, sampled."""
    files = sorted((DS / source).rglob("*.parquet"))
    files = [f for f in files if "labels" not in f.name]
    if not files:
        print(f"  (skip {source}: not downloaded)")
        return
    rng = random.Random(seed)
    per_file = None if limit is None else max(1, limit // len(files))
    for f in files:
        pf = pq.ParquetFile(f)
        n = pf.metadata.num_rows
        keep = set(range(n)) if per_file is None or per_file >= n else set(rng.sample(range(n), per_file))
        i = 0
        for batch in pf.iter_batches(batch_size=256):
            for row in batch.to_pylist():
                if i in keep:
                    yield row
                i += 1


def _write(source: str, key: str, x: np.ndarray) -> str:
    d = CLIPS / source
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{key}.flac"
    if not p.exists():
        sf.write(p, x, 16000, format="FLAC", subtype="PCM_16")
    return str(p.relative_to(ROOT.parent)).replace("\\", "/")


def build_asv19_train(limit_spoof=8000):
    out = []
    bona, spoof = 0, 0
    for r in tqdm(_rows("asv19_train", None), desc="asv19 train"):
        is_bona = str(r.get("system_id")) == "-" or r.get("key") == 0
        if not is_bona and spoof >= limit_spoof:
            continue
        x = _decode(r["audio"])
        if x is None or len(x) < 8000:
            continue
        name = r.get("audio_file_name") or f"asv{bona + spoof}"
        out.append(
            {
                "path": _write("asv19_train", name, x),
                "label": "bonafide" if is_bona else "spoof",
                "speaker": r.get("speaker_id", ""),
                "language": "en",
                "generator": "-" if is_bona else r.get("system_id", ""),
                "source": "asv19",
                "split": "",
            }
        )
        bona += is_bona
        spoof += not is_bona
    return out


def build_labelled_eval(source: str, limit: int, prefix: str, language: str):
    out = []
    for i, r in enumerate(tqdm(_rows(source, limit), desc=source)):
        x = _decode(r["audio"])
        if x is None or len(x) < 8000:
            continue
        notes = r.get("notes")
        try:
            notes = json.loads(notes) if isinstance(notes, str) else (notes or {})
        except json.JSONDecodeError:
            notes = {}
        label = "bonafide" if int(r["label"]) == 0 else "spoof"
        key = notes.get("utterance_id") or f"{prefix}{i}"
        out.append(
            {
                "path": _write(source, str(key).replace("/", "_"), x),
                "label": label,
                "speaker": notes.get("speaker", notes.get("speaker_id", "")),
                "language": language,
                "generator": "",
                "source": source,
                "split": "eval",
            }
        )
    return out


def build_indicsynth(limit=6000):
    out = []
    for i, r in enumerate(tqdm(_rows("indicsynth_hi", limit), desc="indicsynth hi")):
        x = _decode(r["audio"])
        if x is None or len(x) < 8000:
            continue
        out.append(
            {
                "path": _write("indicsynth_hi", f"is{i}", x),
                "label": "spoof",
                "speaker": str(r.get("Target Speaker ID", "")),
                "language": "hi",
                "generator": str(r.get("Generative Model", "")),
                "source": "indicsynth",
                "split": "",
            }
        )
    return out


def build_bona_parquet(source: str, limit: int, language: str, speaker_col: str | None = None):
    out = []
    for i, r in enumerate(tqdm(_rows(source, limit), desc=source)):
        x = _decode(r.get("audio"))
        if x is None or len(x) < 8000:
            continue
        out.append(
            {
                "path": _write(source, f"{source}{i}", x),
                "label": "bonafide",
                "speaker": str(r.get(speaker_col, "")) if speaker_col else f"{source}{r.get('id', i)}",
                "language": language,
                "generator": "-",
                "source": source,
                "split": "",
            }
        )
    return out


def build_mlaad(limit=3000):
    out = []
    files = sorted((DS / "mlaad_hi").rglob("*.wav"))
    rng = random.Random(0)
    for p in tqdm(rng.sample(files, min(limit, len(files))) if files else [], desc="mlaad hi"):
        x, sr = sf.read(p, dtype="float32", always_2d=True)
        x = resample(x.mean(axis=1), sr, 16000)[: int(MAX_S * 16000)]
        gen = p.parent.name
        out.append(
            {
                "path": _write("mlaad_hi", f"{gen}_{p.stem}"[:120], x),
                "label": "spoof",
                "speaker": "",
                "language": "hi",
                "generator": gen,
                "source": "mlaad",
                "split": "",
            }
        )
    return out


def build_replaydf():
    """ReplayDF (English): real and MLAAD-generated speech already played through a loudspeaker and
    re-recorded, so it is benchmarked through the codec only. Extra columns name the setup."""
    out = []
    for meta in sorted((DS / "replaydf" / "wav").glob("*/meta.csv")):
        with open(meta, encoding="utf-8", newline="") as f:
            rows = [r for r in csv.DictReader(f, delimiter="|") if r["language"] == "en"]
        for r in rows:
            p = DS / "replaydf" / r["recorded_file"]
            if not p.exists():
                continue
            x, sr = sf.read(p, dtype="float32", always_2d=True)
            x = resample(x.mean(axis=1), sr, 16000)[: int(MAX_S * 16000)]
            bona = r["label"] == "bona-fide"
            parts = r["original_file"].split("/")
            out.append(
                {
                    "path": _write("replaydf", f"{r['uid']}_{p.stem}", x),
                    "label": "bonafide" if bona else "spoof",
                    # M-AILABS paths are <lang>/by_book/<gender>/<speaker>/...; MLAAD ones fake/<lang>/<model>/...
                    "speaker": parts[3] if bona and len(parts) > 4 else r["architecture"],
                    "language": "en",
                    "generator": "-" if bona else r["architecture"],
                    "source": "replaydf",
                    "split": "eval",
                    "setup": r["uid"],
                    "mic": r["mic"],
                    "loudspeaker": r["speaker"],
                }
            )
    return out


def split_train_dev(rows: list[dict], dev_frac=0.1, seed=0):
    """Per source, hold out whole speakers (or generators when speakers are unknown) for dev,
    until about dev_frac of that source's rows are in dev."""
    rng = random.Random(seed)
    for src in sorted({r["source"] for r in rows}):
        sub = [r for r in rows if r["source"] == src]

        def key(r: dict) -> str:
            return r["speaker"] or r["generator"] or r["path"]

        groups = sorted({key(r) for r in sub})
        rng.shuffle(groups)
        size = {g: 0 for g in groups}
        for r in sub:
            size[key(r)] += 1
        dev, n = set(), 0
        for g in groups:
            if n >= dev_frac * len(sub):
                break
            dev.add(g)
            n += size[g]
        for r in sub:
            r["split"] = "dev" if key(r) in dev else "train"
    return rows


def write(name: str, rows: list[dict], extra: tuple[str, ...] = ()):
    MAN.mkdir(parents=True, exist_ok=True)
    with open(MAN / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, [*FIELDS, *extra])
        w.writeheader()
        w.writerows(rows)
    nb = sum(r["label"] == "bonafide" for r in rows)
    print(f"{name}: {len(rows)} rows ({nb} bonafide, {len(rows) - nb} spoof)")


if __name__ == "__main__":
    import sys

    if "--replaydf" in sys.argv:
        write("replaydf", build_replaydf(), extra=("setup", "mic", "loudspeaker"))
        sys.exit(0)
    if "--resplit" in sys.argv:
        pool = [r for n in ("train", "dev") for r in read(MAN / f"{n}.csv")]
        pool = split_train_dev(pool)
        write("train", [r for r in pool if r["split"] == "train"])
        write("dev", [r for r in pool if r["split"] == "dev"])
        sys.exit(0)
    pool = []
    pool += build_asv19_train()
    pool += build_indicsynth()
    pool += build_bona_parquet("fleurs_hi", 3000, "hi", speaker_col=None)
    pool += build_bona_parquet("kathbath_hi", 4000, "hi", speaker_col="speaker_id")
    pool += build_mlaad()
    pool = split_train_dev(pool)
    write("train", [r for r in pool if r["split"] == "train"])
    write("dev", [r for r in pool if r["split"] == "dev"])
    write("asv19_eval", build_labelled_eval("asv19_eval", 4000, "asv", "en"))
    write("itw", build_labelled_eval("itw", 4000, "itw", "en"))
