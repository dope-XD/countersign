"""S2: speaker drift inside one call.

An ECAPA-TDNN embedding per window is compared with the running mean of the earlier
windows of the same call. A jump suggests a hand-over to a TTS voice or a conversion
glitch. Embeddings live only in the CallDrift object and are dropped when the call ends.
No voiceprint is enrolled or stored anywhere.

Live calls share one GPU worker, batched like S1: ECAPA takes ~10 ms for one window and
~2.5 ms per window in a batch of 8, so batching keeps it from queueing calls behind S1.
"""

from __future__ import annotations

import logging

import numpy as np

from engine.config import settings
from engine.signals.s1_synth import MicroBatcher

log = logging.getLogger(__name__)


class SpeakerEmbedder:
    def __init__(self):
        self.model = None
        self.available = False
        self._batcher = MicroBatcher(self._embed, "s2-gpu")

    def load(self) -> None:
        if not settings.s2_enabled:
            return
        try:
            import torch
            import torchaudio

            if not hasattr(torchaudio, "list_audio_backends"):  # removed in torchaudio 2.9; speechbrain still asks
                torchaudio.list_audio_backends = lambda: ["soundfile"]
            from speechbrain.inference.speaker import EncoderClassifier
            from speechbrain.utils.fetching import LocalStrategy

            device = "cuda" if settings.device == "cuda" and torch.cuda.is_available() else "cpu"
            self.model = EncoderClassifier.from_hparams(
                source="speechbrain/spkrec-ecapa-voxceleb",
                savedir=str(settings.models_dir / "hf" / "ecapa"),
                run_opts={"device": device},
                local_strategy=LocalStrategy.COPY,
            )
            self.available = True
            log.info("S2 ECAPA loaded on %s", device)
        except Exception as e:
            log.warning("S2 unavailable: %s", e)

    def embed(self, windows: list[np.ndarray]) -> list[np.ndarray | None]:
        """Unit-length embeddings, one per window. Safe from any thread."""
        if not self.available or not windows:
            return [None] * len(windows)
        return list(self._batcher(windows))

    def _embed(self, windows: list[np.ndarray]) -> np.ndarray:
        """One ECAPA pass per window length in the batch (live windows all share one length)."""
        import torch

        by_len: dict[int, list[int]] = {}
        for i, w in enumerate(windows):
            by_len.setdefault(len(w), []).append(i)
        rows: list[np.ndarray | None] = [None] * len(windows)
        for idx in by_len.values():
            x = torch.from_numpy(np.stack([windows[i] for i in idx]))
            with torch.inference_mode():
                e = self.model.encode_batch(x).squeeze(1).float().cpu().numpy()
            for i, row in zip(idx, e, strict=True):
                rows[i] = row
        e = np.stack(rows)
        e /= np.linalg.norm(e, axis=1, keepdims=True) + 1e-9
        return e


embedder = SpeakerEmbedder()


class CallDrift:
    """Per-call drift tracker. Holds embeddings in memory only."""

    def __init__(self):
        self._sum: np.ndarray | None = None
        self._n = 0
        self.history: list[float] = []

    def update(self, emb: np.ndarray | None) -> float | None:
        if emb is None:
            return None
        drift = None
        if self._n >= 1:
            ref = self._sum / (np.linalg.norm(self._sum) + 1e-9)
            drift = float(1.0 - np.dot(ref, emb))
            self.history.append(drift)
        self._sum = emb.copy() if self._sum is None else self._sum + emb
        self._n += 1
        return drift

    def max_recent(self, k: int = 5) -> float | None:
        return max(self.history[-k:]) if self.history else None

    def wipe(self) -> None:
        self._sum = None
        self._n = 0
        self.history.clear()
