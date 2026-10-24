"""Real phone-mic recordings: caller-track WAVs captured on a phone during an in-app call.

    data/ota/genuine/<speaker>/*.wav              a person talking into the phone
    data/ota/ai_<generator>/<voice>/*.wav         an AI voice played from a speaker into the phone
    data/ota/labels.csv (optional)                file,label[,speaker,language] for files kept elsewhere
                                                  under data/ota; label is genuine or ai:<generator>

Windows folder names can't hold ":", so a folder says ai_<generator> (or ai-<generator>); labels.csv
may use the ai:<generator> form. The folder under the label is the speaker (or voice); files lying
directly in the label folder use their own name instead.

    python -m ml.ota_recordings      -> data/manifests/ota_real.csv

The audio has already been through the phone's mic, noise suppressor, AGC and codec, so it is
benchmarked and calibrated as is ("clean" channel):

    python -m ml.eval.benchmark --manifest data/manifests/ota_real.csv --split test --channels clean --name "Phone mic recordings"
    python -m ml.calibrate_s1 ... --extra data/manifests/ota_real.csv     (adds its train split)

Splits hold out whole speakers (genuine) and whole generators (AI), so a calibration fitted on
the train split is never scored on a voice or a generator it saw.
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

from ml.build_manifest import FIELDS, MAN
from ml.s1_data import read

ROOT = Path(__file__).resolve().parent.parent
OTA = ROOT / "data" / "ota"
AUDIO = (".wav", ".flac", ".mp3", ".m4a", ".ogg", ".amr", ".3gp")


def parse_label(label: str) -> tuple[str, str] | None:
    """'genuine' -> ('bonafide', '-'); 'ai:x', 'ai_x', 'ai-x' -> ('spoof', 'x'); anything else None."""
    label = label.strip()
    if label.lower() == "genuine":
        return "bonafide", "-"
    for sep in (":", "_", "-"):
        if label.lower().startswith(f"ai{sep}") and len(label) > 3:
            return "spoof", label[3:].strip().lower()
    return None


def scan(root: Path = OTA) -> list[dict]:
    """Every labelled recording under `root`, as manifest rows without a split."""
    rows: dict[str, dict] = {}
    for d in sorted(p for p in root.iterdir() if p.is_dir()) if root.exists() else []:
        lab = parse_label(d.name)
        if lab is None:
            continue
        for f in sorted(d.rglob("*")):
            if f.suffix.lower() in AUDIO:
                speaker = f.parent.name if f.parent != d else f.stem
                rows[str(f)] = _row(f, lab, speaker, "")
    labels = root / "labels.csv"
    if labels.exists():
        for r in read(labels):
            lab, f = parse_label(r.get("label", "")), root / r["file"]
            if lab and f.exists():
                rows[str(f)] = _row(f, lab, r.get("speaker") or f.stem, r.get("language", ""))
    return list(rows.values())


def _row(f: Path, lab: tuple[str, str], speaker: str, language: str) -> dict:
    label, gen = lab
    path = str(f.relative_to(ROOT)).replace("\\", "/") if f.is_relative_to(ROOT) else str(f)
    return {"path": path, "label": label, "speaker": speaker, "language": language, "generator": gen, "source": "ota_real", "split": ""}


def split(rows: list[dict], test_frac: float = 0.5, seed: int = 0) -> list[dict]:
    """Hold out about `test_frac` of genuine speakers and of AI generators, whole, as "test".
    With only one group in a class it goes to test: nothing is fitted on a voice we then score."""
    rng = random.Random(seed)
    for label, key in (("bonafide", "speaker"), ("spoof", "generator")):
        groups = sorted({r[key] for r in rows if r["label"] == label})
        rng.shuffle(groups)
        n_test = max(1, round(test_frac * len(groups))) if groups else 0
        test = set(groups[:n_test])
        for r in rows:
            if r["label"] == label:
                r["split"] = "test" if r[key] in test else "train"
    return rows


def main():
    rows = split(scan())
    MAN.mkdir(parents=True, exist_ok=True)
    with open(MAN / "ota_real.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        w.writerows(rows)
    nb = sum(r["label"] == "bonafide" for r in rows)
    print(f"ota_real: {len(rows)} recordings ({nb} genuine, {len(rows) - nb} AI) -> data/manifests/ota_real.csv")
    if not rows:
        print("  nothing under data/ota yet (see the docstring for the layout)")


if __name__ == "__main__":
    main()
