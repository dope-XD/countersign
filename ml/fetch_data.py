"""Download the dataset subsets used for S1 training and evaluation (~6 GB, non-gated).

    python -m ml.fetch_data            # everything below
    python -m ml.fetch_data itw asv19  # only some
    python -m ml.fetch_data replaydf mlaad_wide

Gated sets (accept terms on the HF page, then `huggingface-cli login`): kathbath, mlaad_hi, mlaad_wide.

Licences (also in docs/ML.md):
  MLAAD     CC BY-NC 4.0, non-commercial; v8+ includes commercial TTS (ElevenLabs, OpenAI, Gemini, ...)
  ReplayDF  CC BY-NC 4.0 per its card (the card's text also names BY-NC-SA); non-commercial research.
            Müller et al., "Replay Attacks Against Audio Deepfake Detection", Interspeech 2025.
            M-AILABS and MLAAD v5 clips played through 109 loudspeaker/microphone pairs.
"""

import random
import sys
from pathlib import Path

from huggingface_hub import HfApi, snapshot_download

ROOT = Path(__file__).resolve().parent.parent / "data" / "datasets"

# ReplayDF setups closest to a laptop playing into a phone: every setup recorded on an iPhone,
# and every setup whose loudspeaker is a laptop's own (English files only, ~0.9 GB)
REPLAYDF_PHONE = ["326c69561d73", "71f98a7edddf", "89e1d39114e4", "8ae17faac9a0", "daa3aa381787", "e7a8d116be51"]
REPLAYDF_LAPTOP = [
    "19041364056f", "8a35c5b6a913", "bd1d784a2975", "dd09de2a982e", "e9f8427e4653", "0afe9a9f46a3", "2a16eaf2ea3d",
    "3335a9bf0fce", "41fe2dd222e1", "4ac5210c9a3c", "8dfeb1ddef8b", "a38f5150185b", "f8d8b766284b", "a920fd7a5acd",
]  # fmt: skip

SETS = {
    "itw": ("SpeechAntiSpoofingBenchmarks/InTheWild", ["data/labels.parquet", "data/test-0000[0-3]-of-00008.parquet"]),
    "asv19_eval": ("SpeechAntiSpoofingBenchmarks/ASVspoof2019_LA", ["data/labels.parquet", "data/test-0000[0-1]-of-00009.parquet"]),
    "asv19_train": ("Bisher/ASVspoof_2019_LA", ["data/train-*"]),
    "indicsynth_hi": (
        "vdivyasharma/IndicSynth",
        ["Hindi/train-00000-of-00107.parquet", "Hindi/train-00053-of-00107.parquet", "Hindi/train-00106-of-00107.parquet"],
    ),
    "fleurs_hi": ("google/fleurs", ["parquet-data/hi_in/train-*", "parquet-data/hi_in/validation-*"]),
    "replaydf": (
        "mueller91/ReplayDF",
        ["README.md", "aux/*/info.txt", "aux/*/RIR.wav", "wav/*/meta.csv"]
        + [p for u in REPLAYDF_PHONE + REPLAYDF_LAPTOP for p in (f"wav/{u}/benign/en/*", f"wav/{u}/spoof/*/en/*")],
    ),
    # gated (auto-approved after you accept the terms on the dataset page)
    "kathbath_hi": ("ai4bharat/Kathbath", ["hindi/valid-*"]),
    "mlaad_hi": ("mueller91/MLAAD", ["fake/hi/IndicF5/*", "fake/hi/VoxCPM2/*", "fake/hi/tts_models_multilingual_multi-dataset_xtts_v2/*"]),
}
DEFAULT = ["itw", "asv19_eval", "asv19_train", "indicsynth_hi", "fleurs_hi"]

# MLAAD systems for the held-out stock-voice test (ml/tts_sets.py `mlaad`): never in train.csv.
# Commercial products first, then open models a scammer can run at home, then all of Hindi.
MLAAD_WIDE = {
    "en": [
        "ElevenLabs-v3", "ElevenLabs-v2-Multilingual", "ElevenLabs-Turbo-v2.5", "OpenAI TTS-1 HD", "Gemini-3.1-Flash-TTS",
        "Edge-TTS", "Cartesia.ai (Sonic-3)", "DeepGram", "MiniMax-Speech-2.8-Turbo", "Resemble.ai (April 12th, 2025)",
        "Inworld-TTS-2", "Rime-Coda", "Smallest-Lightning-v3.1",
        "kokoro", "f5-tts", "Chatterbox", "tts_models_multilingual_multi-dataset_xtts_v2", "suno_bark", "Spark-TTS-0.5B",
        "Index-TTS-2.0", "Higgs-Audio-V2", "Microsoft VibeVoice 1.5B", "OpenVoiceV2", "Qwen3-TTS-12Hz-1.7B-Base", "Llasa-1B",
        "Nari Dia-1.6B", "sesame_csm", "GPT-SoVITS", "MeloTTS",
    ],
    "hi": [
        "IndicF5", "Indri-TTS-0.1", "OmniVoice", "Ringg Squirrel TTS v1.0", "Veena", "VoxCPM2", "Voxtral",
        "tts_models_multilingual_multi-dataset_bark", "tts_models_multilingual_multi-dataset_xtts_v2",
    ],
}  # fmt: skip


def fetch_mlaad_wide(per_system: int = 60, seed: int = 0) -> None:
    """A fixed random sample of `per_system` clips from each MLAAD_WIDE system (plus its meta.csv)."""
    api, rng = HfApi(), random.Random(seed)
    pats = []
    for lang, systems in MLAAD_WIDE.items():
        for s in systems:
            files = sorted(t.path for t in api.list_repo_tree("mueller91/MLAAD", path_in_repo=f"fake/{lang}/{s}", repo_type="dataset"))
            wavs = [f for f in files if f.endswith((".wav", ".mp3", ".flac"))]
            pats += [f for f in files if f.endswith(".csv")] + rng.sample(wavs, min(per_system, len(wavs)))
    snapshot_download("mueller91/MLAAD", repo_type="dataset", allow_patterns=pats, local_dir=ROOT / "mlaad_wide", max_workers=8)


if __name__ == "__main__":
    for name in sys.argv[1:] or DEFAULT:
        print("==>", name, flush=True)
        try:
            if name == "mlaad_wide":
                fetch_mlaad_wide()
                p = ROOT / name
            else:
                repo, pats = SETS[name]
                p = snapshot_download(repo, repo_type="dataset", allow_patterns=pats, local_dir=ROOT / name, max_workers=4)
            print("   ok", p, flush=True)
        except Exception as e:
            print("   FAILED", name, e, flush=True)
