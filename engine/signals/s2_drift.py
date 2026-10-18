"""S2: speaker drift inside one call.

An ECAPA-TDNN embedding per window is compared with the running mean of the earlier
windows of the same call. A jump suggests a hand-over to a TTS voice or a conversion
glitch. Embeddings live only in the CallDrift object and are dropped when the call ends.
No voiceprint is enrolled or stored anywhere.
"""

from __future__ import annotations

import logging
import threading

import numpy as np

from engine.config import settings

log = logging.getLogger(__name__)


class SpeakerEmbedder:
    def __init__(self):
        self.model = None
        self.available = False
        self._lock = threading.Lock()

    def load(self) -> None:
        if not settings.s2_enabled:
            return
        try:
            import torch
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
        if not self.available or not windows:
            return [None] * len(windows)
        import torch

        n = min(len(w) for w in windows)
        x = torch.from_numpy(np.stack([w[:n] for w in windows]))
        with self._lock, torch.inference_mode():
            e = self.model.encode_batch(x).squeeze(1).float().cpu().numpy()
        e /= np.linalg.norm(e, axis=1, keepdims=True) + 1e-9
        return list(e)


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
