"""S1: synthetic-speech probability per 4 s window.

Backends (picked by each checkpoint's "arch" field; several checkpoints form an ensemble):
  sls          - XLS-R + SLS (HF port), weights from models/s1_sls_hf.pt
  antideepfake - NII AntiDeepfake (HF port, ml/port_antideepfake.py)
  dummy - a spectral heuristic so the whole product runs before weights exist.
          The UI labels it clearly; it is never used for reported numbers.

Every live call scores one window every 2 s from its own worker thread. Those calls share
one GPU worker (MicroBatcher): windows that arrive within BATCH_WAIT_S of each other, or pile
up while the GPU is busy, go through the networks as one batch of up to MAX_BATCH. On an
RTX 5070 Laptop the ensemble takes ~39 ms for one window and ~20 ms per window in a batch
of 8 (173 ms), so the GPU cost per window falls as calls are added instead of each call
queueing behind the others; MAX_BATCH keeps one pass well inside the 300 ms window budget.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from engine.config import settings

log = logging.getLogger(__name__)
MAX_BATCH = 8  # windows per forward pass
BATCH_WAIT_S = 0.02  # how long the oldest queued window waits for company before the GPU runs


@dataclass
class S1Result:
    p_synthetic: float
    ms: float  # per window, as the caller saw it: waiting for the GPU worker + the forward pass


@dataclass
class _Job:
    """One caller's windows waiting for the GPU worker."""

    windows: list[np.ndarray]
    t0: float = field(default_factory=time.perf_counter)
    done: threading.Event = field(default_factory=threading.Event)
    out: np.ndarray | None = None
    error: BaseException | None = None


class MicroBatcher:
    """Runs `fn` (windows -> array with one row per window) on one worker thread for callers
    on any number of threads. The worker takes the oldest job, adds whatever else arrives
    before that job has waited `wait_s` (up to `max_batch` windows), makes one call to `fn`
    and hands each caller its own rows. A job bigger than max_batch runs alone."""

    def __init__(self, fn, name: str, max_batch: int = MAX_BATCH, wait_s: float = BATCH_WAIT_S):
        self.fn, self.name, self.max_batch, self.wait_s = fn, name, max_batch, wait_s
        self.batch_sizes: list[int] = []  # windows per call to fn, last 2000; replaced, never mutated
        self._jobs: queue.Queue[_Job] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._start = threading.Lock()

    def __call__(self, windows: list[np.ndarray]) -> np.ndarray:
        job = _Job(list(windows))
        with self._start:
            if self._worker is None:
                self._worker = threading.Thread(target=self._run, name=self.name, daemon=True)
                self._worker.start()
        self._jobs.put(job)
        job.done.wait()
        if job.error is not None:
            raise job.error
        return job.out

    def _run(self) -> None:
        carry: _Job | None = None  # a job that would have overfilled the last batch
        since, sizes = time.perf_counter(), []
        while True:
            batch = [carry or self._jobs.get()]
            carry = None
            n = len(batch[0].windows)
            deadline = batch[0].t0 + self.wait_s
            while n < self.max_batch:
                try:
                    job = self._jobs.get(timeout=max(0.0, deadline - time.perf_counter()))
                except queue.Empty:
                    break
                if n + len(job.windows) > self.max_batch:
                    carry = job
                    break
                batch.append(job)
                n += len(job.windows)
            try:
                out = self.fn([w for j in batch for w in j.windows])
                i = 0
                for j in batch:
                    j.out, i = out[i : i + len(j.windows)], i + len(j.windows)
            except BaseException as e:  # every waiting caller gets the error, the worker carries on
                for j in batch:
                    j.error = e
            finally:
                for j in batch:
                    j.done.set()
            self.batch_sizes = (self.batch_sizes + [n])[-2000:]
            sizes.append(n)
            if time.perf_counter() - since >= 30:
                log.info(
                    "%s: %d windows in %d batches over the last %.0f s (mean %.1f, max %d)",
                    self.name,
                    sum(sizes),
                    len(sizes),
                    time.perf_counter() - since,
                    np.mean(sizes),
                    max(sizes),
                )
                since, sizes = time.perf_counter(), []


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
        self.batcher = MicroBatcher(lambda ws: self._features(ws), "s1-gpu")
        self._lat_lock = threading.Lock()
        self.latencies_ms: list[float] = []  # replaced, never mutated, so readers need no lock
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
        # Warm-up so the first live window isn't slow, and a full batch so its memory is
        # claimed (or fails) now rather than on the first busy minute
        self.features([np.zeros(64600, dtype=np.float32)] * self.batcher.max_batch)
        self.score([np.zeros(64600, dtype=np.float32)])
        self.latencies_ms, self.batcher.batch_sizes = [], []
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
        """Uncalibrated spoof log-odds, one column per model: (N, M). Used to fit the calibration.
        Safe from any thread: the windows join the GPU worker's next batch."""
        return self.batcher(windows)

    def log_odds(self, windows: list[np.ndarray]) -> list[float]:
        """Uncalibrated spoof log-odds of the first model."""
        return self.features(windows)[:, 0].tolist()

    def score(self, windows: list[np.ndarray]) -> list[S1Result]:
        if not windows:
            return []
        t0 = time.perf_counter()
        if self.models:
            z = np.clip(self.features(windows), -60, 60) @ self.calib_w + self.calib_b
            probs = (1 / (1 + np.exp(-z))).tolist()
        else:
            probs = [_dummy_score(w) for w in windows]
        ms = (time.perf_counter() - t0) * 1000 / len(windows)
        with self._lat_lock:
            self.latencies_ms = (self.latencies_ms + [ms] * len(windows))[-2000:]
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
        lat = self.latencies_ms
        if not lat:
            return None
        return float(np.percentile(lat, 95))


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
