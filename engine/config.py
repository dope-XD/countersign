"""Runtime settings. Everything can be overridden with COUNTERSIGN_* environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _env(name: str, default: str) -> str:
    return os.environ.get(f"COUNTERSIGN_{name}", default)


def _default_s1() -> str:
    """The best S1 on disk. The AntiDeepfake W2V-Large + XLS-R-1B ensemble won the phone-channel
    benchmark (docs/ML.md); then the phone/Indic SLS fine-tune; then the published SLS port."""
    m = ROOT / "models"
    ensemble = [m / "s1_add_w2vlarge.pt", m / "s1_add_xlsr1b.pt"]
    if all(p.exists() for p in ensemble):
        return ",".join(str(p) for p in ensemble)
    return str(m / ("s1_sls_phone.pt" if (m / "s1_sls_phone.pt").exists() else "s1_sls_hf.pt"))


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path(_env("DATA", str(ROOT / "data")))
    models_dir: Path = Path(_env("MODELS", str(ROOT / "models")))
    runtime_dir: Path = Path(_env("RUNTIME", str(ROOT / "data" / "runtime")))
    web_dist: Path = ROOT / "web" / "dist"

    # Detector. "dummy" scores with a heuristic so the pipeline runs without weights.
    s1_backend: str = _env("S1", "auto")  # auto | dummy | sls/antideepfake (fail if the checkpoint will not load)
    # comma-separated checkpoints form an ensemble; see _default_s1() for the order of preference
    s1_checkpoint: Path = Path(_env("S1_CKPT", _default_s1()))
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

    # Where phones reach this engine (the HTTPS tunnel), for the QR codes on /demo. Empty =
    # the address the demo page itself was opened on.
    public_url: str = _env("PUBLIC_URL", "")

    # Staff PIN for the agent console, fraud desk, demo panel and metrics. Generated and
    # printed on first run if unset (kept in runtime/staff_pin.txt).
    staff_pin: str = _env("STAFF_PIN", "")
    # The softphone needs no login (the caller may be the attacker) and every call costs GPU
    # time, so a public engine takes at most this many live calls at once.
    max_live_calls: int = int(_env("MAX_CALLS", "4"))
    # dev server only: sign-up also takes Android emulator numbers (+1 555 521 5554) so `adb emu gsm call` matches
    allow_test_numbers: bool = _env("ALLOW_TEST_NUMBERS", "0") == "1"

    # Amazon Connect ingest (engine/ingest/connect.py). The secret is the Lambda's
    # CONNECT_HMAC_SECRET; empty turns the endpoint off. The AWS profile (or the usual AWS_*
    # variables) needs kinesisvideo:GetDataEndpoint and GetMedia on the Connect streams.
    connect_secret: str = _env("CONNECT_SECRET", "")
    connect_aws_profile: str = _env("CONNECT_AWS_PROFILE", "")

    # The app's APK, offered for download at /download/cs-bank.apk (app/cs-bank.apk).
    app_dir: Path = Path(_env("APP_DIR", str(ROOT / "data" / "app")))
    eval_mode: bool = _env("EVAL", "0") == "1"

    # Mock KMS: a 32-byte hex key. Generated on first run if absent.
    evidence_key_hex: str = _env("EVIDENCE_KEY", "")
    evidence_seconds: float = 20.0
    evidence_retention_days: int = 30


settings = Settings()
settings.runtime_dir.mkdir(parents=True, exist_ok=True)
