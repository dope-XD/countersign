"""The server's speech-to-text for the stronger check: Omnilingual ASR 1B CTC (int8) on sherpa-onnx, larger than the
phone's 300M model; falls back to the 300M model when the 1B one isn't downloaded. Audio in, text out, nothing kept."""

from __future__ import annotations

import threading
from functools import cache
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
ASR = ROOT / "data" / "datasets" / "asr"
MODELS = [
    "sherpa-onnx-omnilingual-asr-1600-languages-1B-ctc-v2-int8-2026-02-05",
    "sherpa-onnx-omnilingual-asr-1600-languages-300M-ctc-v2-int8-2026-02-05",
]
_lock = threading.Lock()


@cache
def recognizer():
    import sherpa_onnx as so

    for name in MODELS:
        d = ASR / name
        if (d / "model.int8.onnx").exists():
            return name, so.OfflineRecognizer.from_omnilingual_asr_ctc(model=str(d / "model.int8.onnx"), tokens=str(d / "tokens.txt"), num_threads=4)
    raise FileNotFoundError("no Omnilingual model in data/datasets/asr (python -m ml.eval.asr_bakeoff downloads instructions)")


def model_name() -> str:
    try:
        return recognizer()[0]
    except FileNotFoundError:
        return "none"


def transcribe(audio: np.ndarray, lang: str | None = None) -> str:
    _, rec = recognizer()
    with _lock:
        s = rec.create_stream()
        s.accept_waveform(16000, audio.astype(np.float32))
        rec.decode_stream(s)
        return s.result.text.strip()
