"""Streaming voice activity detection per track (Silero VAD, energy fallback).

Runs on the 8 kHz line audio as it arrives and tracks speech onsets and offsets in
absolute sample positions, so S3 can time how long a caller takes to start answering.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

log = logging.getLogger(__name__)

# Silero takes fixed chunks: 256 samples at 8 kHz or 512 at 16 kHz (32 ms either way)
CHUNK_FOR_RATE = {8000: 256, 16000: 512}
_silero_factory = None


def _load_silero():
    global _silero_factory
    if _silero_factory is None:
        try:
            from silero_vad import load_silero_vad

            load_silero_vad()  # warm the cache once
            _silero_factory = load_silero_vad
        except Exception as e:  # pragma: no cover - fallback path
            log.warning("Silero VAD unavailable (%s); using energy VAD", e)
            _silero_factory = False
    return _silero_factory


@dataclass
class Segment:
    start: int
    end: int | None = None


@dataclass
class StreamingVAD:
    sample_rate: int = 8000
    threshold: float = 0.5
    min_silence_chunks: int = 8  # ~250 ms of silence closes a segment
    min_speech_chunks: int = 3  # ~100 ms of speech opens one
    pos: int = 0  # absolute samples consumed
    flags: list[bool] = field(default_factory=list)  # one per chunk, whole call (tiny)
    segments: list[Segment] = field(default_factory=list)
    _pending: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float32))
    _speech_run: int = 0
    _silence_run: int = 0

    def __post_init__(self):
        if self.sample_rate not in CHUNK_FOR_RATE:
            raise ValueError(f"VAD supports {sorted(CHUNK_FOR_RATE)} Hz, not {self.sample_rate}")
        self.chunk = CHUNK_FOR_RATE[self.sample_rate]
        factory = _load_silero()
        self._model = factory() if factory else None

    @property
    def in_speech(self) -> bool:
        return bool(self.segments) and self.segments[-1].end is None

    def _prob(self, chunk: np.ndarray) -> float:
        if self._model is not None:
            import torch

            with torch.no_grad():
                return float(self._model(torch.from_numpy(chunk), self.sample_rate).item())
        rms = float(np.sqrt(np.mean(chunk**2)) + 1e-9)
        return 1.0 if 20 * np.log10(rms) > -42 else 0.0

    def feed(self, x: np.ndarray) -> list[tuple[str, int]]:
        """Feed audio at `sample_rate`. Returns events [("onset"|"offset", abs_sample)]."""
        events: list[tuple[str, int]] = []
        buf = np.concatenate([self._pending, x]) if len(self._pending) else x
        c = self.chunk
        n = len(buf) // c
        for i in range(n):
            speech = self._prob(np.ascontiguousarray(buf[i * c : (i + 1) * c])) >= self.threshold
            self.flags.append(speech)
            chunk_start = self.pos
            self.pos += c
            if speech:
                self._speech_run += 1
                self._silence_run = 0
                if not self.in_speech and self._speech_run >= self.min_speech_chunks:
                    onset = chunk_start - (self.min_speech_chunks - 1) * c
                    self.segments.append(Segment(start=onset))
                    events.append(("onset", onset))
            else:
                self._silence_run += 1
                self._speech_run = 0
                if self.in_speech and self._silence_run >= self.min_silence_chunks:
                    offset = self.pos - self._silence_run * c
                    self.segments[-1].end = offset
                    events.append(("offset", offset))
        self._pending = buf[n * c :].copy()
        return events

    def voiced_fraction(self, t0: int, t1: int) -> float:
        a, b = max(t0 // self.chunk, 0), min(t1 // self.chunk, len(self.flags))
        if b <= a:
            return 0.0
        return float(np.mean(self.flags[a:b]))

    def reset(self) -> None:
        if self._model is not None and hasattr(self._model, "reset_states"):
            self._model.reset_states()
        self.flags.clear()
        self.segments.clear()
        self.pos = 0
        self._pending = np.zeros(0, dtype=np.float32)
        self._speech_run = 0
        self._silence_run = 0
