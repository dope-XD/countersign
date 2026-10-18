"""Runtime settings. Everything can be overridden with COUNTERSIGN_* environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _env(name: str, default: str) -> str:
    return os.environ.get(f"COUNTERSIGN_{name}", default)


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path(_env("DATA", str(ROOT / "data")))
    models_dir: Path = Path(_env("MODELS", str(ROOT / "models")))
    runtime_dir: Path = Path(_env("RUNTIME", str(ROOT / "data" / "runtime")))
    web_dist: Path = ROOT / "web" / "dist"

    # Detector. "dummy" scores with a heuristic so the pipeline runs without weights.
    s1_backend: str = _env("S1", "auto")  # auto | sls | dummy
    # the phone/Indic fine-tune when it exists, else the converted published checkpoint
    s1_checkpoint: Path = Path(
        _env("S1_CKPT", str(ROOT / "models" / ("s1_sls_phone.pt" if (ROOT / "models" / "s1_sls_phone.pt").exists() else "s1_sls_hf.pt")))
    )
    s2_enabled: bool = _env("S2", "1") == "1"
    asr_model: str = _env("ASR", "small")
    device: str = _env("DEVICE", "cuda")

    # Audio framing (deck: 4 s windows every 2 s from a 20 s rolling buffer)
    sample_rate: int = 16000
    line_rate: int = 8000
    window_samples: int = 64600  # what the SLS head was built for (~4.04 s)
    hop_seconds: float = 2.0
    buffer_seconds: float = 20.0
    min_voiced_fraction: float = 0.35

    # Fusion cut-offs (deck: GREEN < 0.30, AMBER 0.30-0.70, RED >= 0.70)
    amber_at: float = float(_env("AMBER_AT", "0.30"))
    red_at: float = float(_env("RED_AT", "0.70"))

    # WebAuthn. RP ID must be the hostname the phones load the app from.
    rp_id: str = _env("RP_ID", "auto")  # "auto" = the Host the page was loaded from
    rp_name: str = "Countersign Bank"
    origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(o.strip() for o in _env("ORIGINS", "http://localhost:8000,http://localhost:5173").split(",") if o.strip())
    )

    # Staff PIN for the agent console, fraud desk, demo panel and metrics. Generated and
    # printed on first run if unset (kept in runtime/staff_pin.txt).
    staff_pin: str = _env("STAFF_PIN", "")
    eval_mode: bool = _env("EVAL", "0") == "1"

    # Mock KMS: a 32-byte hex key. Generated on first run if absent.
    evidence_key_hex: str = _env("EVIDENCE_KEY", "")
    evidence_seconds: float = 20.0
    evidence_retention_days: int = 30


settings = Settings()
settings.runtime_dir.mkdir(parents=True, exist_ok=True)
