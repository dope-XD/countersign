"""S1: synthetic-speech probability per 4 s window.

Backends:
  sls   - XLS-R + SLS (HF port), weights from models/s1_sls_hf.pt
  dummy - a spectral heuristic so the whole product runs before weights exist.
          The UI labels it clearly; it is never used for reported numbers.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

import numpy as np

from engine.config import settings

log = logging.getLogger(__name__)


@dataclass
class S1Result:
    p_synthetic: float
    ms: float


class S1Detector:
    def __init__(self):
        self.backend = "dummy"
        self.version = "dummy-0"
        self.model = None
        self.device = "cpu"
        self._lock = threading.Lock()  # one GPU, one window at a time
        self.latencies_ms: list[float] = []
        self.calib = (1.0, 0.0)  # p = sigmoid(a * log-odds + b), fitted by ml/calibrate_s1.py
        self.calibrated = False

    def load(self) -> None:
        want = settings.s1_backend
        if want in ("auto", "sls") and settings.s1_checkpoint.exists():
            try:
                self._load_sls()
                return
            except Exception:
                if want == "sls":
                    raise
                log.exception("Could not load SLS checkpoint, falling back to dummy")
        elif want == "sls":
            raise FileNotFoundError(settings.s1_checkpoint)
        log.warning("S1 running the DUMMY scorer. Results are not meaningful.")

    def _load_sls(self) -> None:
        import torch

        from engine.signals.sls_model import SLSModel

        self.device = "cuda" if settings.device == "cuda" and torch.cuda.is_available() else "cpu"
        ckpt = torch.load(settings.s1_checkpoint, map_location="cpu", weights_only=False)
        model = SLSModel()
        state = ckpt["state_dict"] if "state_dict" in ckpt else ckpt
        model.load_state_dict(state, strict=True)
        model.eval().to(self.device)
        if self.device == "cuda":
            model.half()
        self.model = model
        self.backend = "sls"
        self.version = ckpt.get("version", settings.s1_checkpoint.stem) if isinstance(ckpt, dict) else "sls"
        self._load_calibration()
        # Warm-up so the first live window isn't slow
        self.score([np.zeros(64600, dtype=np.float32)])
        self.latencies_ms.clear()
        log.info("S1 loaded %s on %s", self.version, self.device)

    def _load_calibration(self) -> None:
        import json

        p = settings.models_dir / "s1_calibration.json"
        if p.exists():
            c = json.loads(p.read_text()).get(self.version)  # one entry per model version
            if c:
                self.calib = (float(c["a"]), float(c["b"]))
                self.calibrated = True
                log.info("S1 calibration a=%.3f b=%.3f (dev EER %s)", *self.calib, c.get("dev_eer"))
                return
            log.warning("s1_calibration.json has no entry for %s; using raw scores", self.version)
        else:
            log.warning("No S1 calibration found; raw scores are badly calibrated (run ml/calibrate_s1.py)")

    def log_odds(self, windows: list[np.ndarray]) -> list[float]:
        """Uncalibrated spoof log-odds (used to fit the calibration)."""
        with self._lock:
            return self._logodds_sls(windows)

    def score(self, windows: list[np.ndarray]) -> list[S1Result]:
        if not windows:
            return []
        t0 = time.perf_counter()
        with self._lock:
            if self.backend == "sls":
                probs = self._score_sls(windows)
            else:
                probs = [_dummy_score(w) for w in windows]
        ms = (time.perf_counter() - t0) * 1000 / len(windows)
        self.latencies_ms.extend([ms] * len(windows))
        self.latencies_ms = self.latencies_ms[-2000:]
        return [S1Result(p, ms) for p in probs]

    def _score_sls(self, windows: list[np.ndarray]) -> list[float]:
        a, b = self.calib
        z = np.asarray(self._logodds_sls(windows))
        return (1 / (1 + np.exp(-(a * z + b)))).tolist()

    def _logodds_sls(self, windows: list[np.ndarray]) -> list[float]:
        import torch

        from engine.signals.sls_model import fit_length

        x = torch.stack([fit_length(torch.from_numpy(np.ascontiguousarray(w))) for w in windows])
        x = x.to(self.device)
        if self.device == "cuda":
            x = x.half()
        with torch.inference_mode():
            logp = self.model(x).float()
        # column 0 = spoof, 1 = bona fide
        return (logp[:, 0] - logp[:, 1]).cpu().tolist()

    def p95_ms(self) -> float | None:
        if not self.latencies_ms:
            return None
        return float(np.percentile(self.latencies_ms, 95))


def _dummy_score(w: np.ndarray) -> float:
    """Placeholder: spectral flatness above 3.4 kHz (phone band edge). Not a detector."""
    if len(w) < 2048 or np.max(np.abs(w)) < 1e-4:
        return 0.0
    spec = np.abs(np.fft.rfft(w[:16384] * np.hanning(min(len(w), 16384))))
    hi = spec[int(len(spec) * 3400 / 8000) :] + 1e-9
    flat = float(np.exp(np.mean(np.log(hi))) / np.mean(hi))
    return float(np.clip(flat * 1.6, 0, 1))


detector = S1Detector()
