"""S1: synthetic-speech probability per 4 s window.

Backends (picked by each checkpoint's "arch" field; several checkpoints form an ensemble):
  sls          - XLS-R + SLS (HF port), weights from models/s1_sls_hf.pt
  antideepfake - NII AntiDeepfake (HF port, ml/port_antideepfake.py)
  dummy - a spectral heuristic so the whole product runs before weights exist.
          The UI labels it clearly; it is never used for reported numbers.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from engine.config import settings

log = logging.getLogger(__name__)


@dataclass
class S1Result:
    p_synthetic: float
    ms: float


class S1Detector:
    """One model, or a score-level ensemble of several (checkpoint paths joined by commas).

    Each model gives a spoof log-odds per window. The calibration in models/s1_calibration.json,
    keyed by the version string ("v1" or "v1+v2"), maps them to a probability:
    p = sigmoid(w . z + b), fitted on the dev split by ml/calibrate_s1.py."""

    def __init__(self):
        self.backend = "dummy"
        self.version = "dummy-0"
        self.models: list = []
        self.device = "cpu"
        self._lock = threading.Lock()  # one GPU, one window at a time
        self.latencies_ms: list[float] = []
        self.calib_w = np.ones(1)
        self.calib_b = 0.0
        self.calibrated = False

    @property
    def model(self):
        """The first (or only) network; None when running the dummy scorer."""
        return self.models[0] if self.models else None

    def load(self, checkpoint: Path | str | None = None) -> None:
        """Load S1. `checkpoint` overrides settings.s1_checkpoint (used by the ML scripts)."""
        want = "model" if checkpoint else settings.s1_backend
        paths = [Path(c) for c in str(checkpoint or settings.s1_checkpoint).split(",")]
        if want != "dummy" and all(p.exists() for p in paths):
            try:
                self._load_models(paths)
                return
            except Exception:
                if want != "auto":
                    raise
                log.exception("Could not load S1 checkpoint, falling back to dummy")
        elif want != "auto" and want != "dummy":
            raise FileNotFoundError(paths)
        log.warning("S1 running the DUMMY scorer. Results are not meaningful.")

    def _load_models(self, paths: list[Path]) -> None:
        import torch

        self.device = "cuda" if settings.device == "cuda" and torch.cuda.is_available() else "cpu"
        models, archs, versions = [], [], []
        for path in paths:
            ckpt = torch.load(path, map_location="cpu", weights_only=False)
            model, arch = build_model(ckpt)
            model.load_state_dict(ckpt.get("state_dict", ckpt), strict=True)
            model.eval().to(self.device)
            if self.device == "cuda":
                model.half()
            models.append(model)
            archs.append(arch)
            versions.append(ckpt.get("version", path.stem) if isinstance(ckpt, dict) else arch)
            del ckpt
        self.models = models
        self.backend = "+".join(archs)
        self.version = "+".join(versions)
        self.calib_w, self.calib_b, self.calibrated = np.ones(len(models)) / len(models), 0.0, False
        self._load_calibration()
        # Warm-up so the first live window isn't slow
        self.score([np.zeros(64600, dtype=np.float32)])
        self.latencies_ms.clear()
        log.info("S1 loaded %s on %s", self.version, self.device)

    def _load_calibration(self) -> None:
        import json

        p = settings.models_dir / "s1_calibration.json"
        if p.exists():
            c = json.loads(p.read_text()).get(self.version)  # one entry per model version (or ensemble)
            if c:
                w = c["w"] if "w" in c else [c["a"]]
                if len(w) == len(self.models):
                    self.calib_w, self.calib_b, self.calibrated = np.asarray(w, dtype=np.float64), float(c["b"]), True
                    log.info("S1 calibration w=%s b=%.3f (dev EER %s)", np.round(self.calib_w, 3).tolist(), self.calib_b, c.get("dev_eer"))
                    return
            log.warning("s1_calibration.json has no entry for %s; using raw scores", self.version)
        else:
            log.warning("No S1 calibration found; raw scores are badly calibrated (run ml/calibrate_s1.py)")

    def features(self, windows: list[np.ndarray]) -> np.ndarray:
        """Uncalibrated spoof log-odds, one column per model: (N, M). Used to fit the calibration."""
        with self._lock:
            return self._features(windows)

    def log_odds(self, windows: list[np.ndarray]) -> list[float]:
        """Uncalibrated spoof log-odds of the first model."""
        return self.features(windows)[:, 0].tolist()

    def score(self, windows: list[np.ndarray]) -> list[S1Result]:
        if not windows:
            return []
        t0 = time.perf_counter()
        with self._lock:
            if self.models:
                z = np.clip(self._features(windows), -60, 60) @ self.calib_w + self.calib_b
                probs = (1 / (1 + np.exp(-z))).tolist()
            else:
                probs = [_dummy_score(w) for w in windows]
        ms = (time.perf_counter() - t0) * 1000 / len(windows)
        self.latencies_ms.extend([ms] * len(windows))
        self.latencies_ms = self.latencies_ms[-2000:]
        return [S1Result(p, ms) for p in probs]

    def _features(self, windows: list[np.ndarray]) -> np.ndarray:
        import torch

        from engine.signals.sls_model import fit_length

        x = torch.stack([fit_length(torch.from_numpy(np.ascontiguousarray(w))) for w in windows])
        x = x.to(self.device)
        if self.device == "cuda":
            x = x.half()
        cols = []
        with torch.inference_mode():
            for model in self.models:
                out = model(x).float()
                # both architectures put spoof in column 0 and bona fide in column 1
                # (SLS: log-probabilities, AntiDeepfake: logits), so the difference is the spoof log-odds
                cols.append((out[:, 0] - out[:, 1]).cpu().numpy())
        return np.stack(cols, axis=1).astype(np.float64)

    def p95_ms(self) -> float | None:
        if not self.latencies_ms:
            return None
        return float(np.percentile(self.latencies_ms, 95))


def build_model(ckpt: dict):
    """The network for a converted checkpoint, from its "arch" field (old SLS files have none)."""
    arch = ckpt.get("arch", "sls") if isinstance(ckpt, dict) else "sls"
    if arch == "antideepfake":
        from engine.signals.antideepfake_model import AntiDeepfakeModel, backbone_config

        return AntiDeepfakeModel(backbone_config(ckpt["config"])), arch
    from engine.signals.sls_model import SLSModel

    return SLSModel(), "sls"


def _dummy_score(w: np.ndarray) -> float:
    """Placeholder: spectral flatness above 3.4 kHz (phone band edge). Not a detector."""
    if len(w) < 2048 or np.max(np.abs(w)) < 1e-4:
        return 0.0
    spec = np.abs(np.fft.rfft(w[:16384] * np.hanning(min(len(w), 16384))))
    hi = spec[int(len(spec) * 3400 / 8000) :] + 1e-9
    flat = float(np.exp(np.mean(np.log(hi))) / np.mean(hi))
    return float(np.clip(flat * 1.6, 0, 1))


detector = S1Detector()
