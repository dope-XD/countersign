"""Download the dataset subsets used for S1 training and evaluation (~6 GB, non-gated).

    python -m ml.fetch_data            # everything below
    python -m ml.fetch_data itw asv19  # only some

Gated sets (accept terms on the HF page, then `huggingface-cli login`): kathbath, mlaad_hi.
"""
import sys
from pathlib import Path

from huggingface_hub import snapshot_download

ROOT = Path(__file__).resolve().parent.parent / "data" / "datasets"

SETS = {
    "itw": ("SpeechAntiSpoofingBenchmarks/InTheWild", ["data/labels.parquet", "data/test-0000[0-3]-of-00008.parquet"]),
    "asv19_eval": ("SpeechAntiSpoofingBenchmarks/ASVspoof2019_LA", ["data/labels.parquet", "data/test-0000[0-1]-of-00009.parquet"]),
    "asv19_train": ("Bisher/ASVspoof_2019_LA", ["data/train-*"]),
    "indicsynth_hi": ("vdivyasharma/IndicSynth", ["Hindi/train-00000-of-00107.parquet", "Hindi/train-00053-of-00107.parquet", "Hindi/train-00106-of-00107.parquet"]),
    "fleurs_hi": ("google/fleurs", ["parquet-data/hi_in/train-*", "parquet-data/hi_in/validation-*"]),
    # gated (auto-approved after you accept the terms on the dataset page)
    "kathbath_hi": ("ai4bharat/Kathbath", ["hindi/valid-*"]),
    "mlaad_hi": ("mueller91/MLAAD", ["fake/hi/IndicF5/*", "fake/hi/VoxCPM2/*", "fake/hi/tts_models_multilingual_multi-dataset_xtts_v2/*"]),
}
DEFAULT = ["itw", "asv19_eval", "asv19_train", "indicsynth_hi", "fleurs_hi"]

if __name__ == "__main__":
    for name in sys.argv[1:] or DEFAULT:
        repo, pats = SETS[name]
        print("==>", name, repo, flush=True)
        try:
            p = snapshot_download(repo, repo_type="dataset", allow_patterns=pats, local_dir=ROOT / name, max_workers=4)
            print("   ok", p, flush=True)
        except Exception as e:
            print("   FAILED", name, e, flush=True)
