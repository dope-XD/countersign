"""Build the one model pack the phone downloads (CONTRACT.md, `GET /api/m/models`) and, with --release, publish it.

    python -m ml.pack_models                    # data/pack/countersign-pack-v2.zip + models/pack.json
    python -m ml.pack_models --release          # also upload it to the GitHub release models-v2 (gh CLI)

Inside the zip, flat: the speech-to-text model picked by ml/eval/asr_bakeoff.py, its tokens, Silero VAD, the voice-clone
model from ml/voice_clone.py (if built), the conversation model (ml/conv_model.py) and the base e5 for the move matcher
(ml/moves.py export, int8), and pack.json, which tells the app (Speech.kt, VoiceCheck.kt, ConversationModels.kt) which file
is which. Licences: Omnilingual ASR (Meta) Apache-2.0; Silero VAD MIT; voice-clone model derived from AntiDeepfake,
CC BY-NC-SA 4.0; multilingual-e5-small MIT (our fine-tune trained on ICFD-31k, released for research use).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASR = ROOT / "data" / "datasets" / "asr"
OUT = ROOT / "data" / "pack"
NAME = "countersign-pack-v2"
TAG = "models-v2"
REPO = "dope-XD/countersign"
OMNI = ASR / "sherpa-onnx-omnilingual-asr-1600-languages-300M-ctc-v2-int8-2026-02-05"
VOICE = ROOT / "models" / "voice_clone"
CONV = ROOT / "models" / "conv_model"


def build() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    files = {
        "asr_omnilingual.int8.onnx": OMNI / "model.int8.onnx",
        "asr_omnilingual_tokens.txt": OMNI / "tokens.txt",
        "silero_vad.onnx": ASR / "silero_vad.onnx",
    }
    manifest: dict = {
        "name": NAME,
        "asr": [{"name": "omnilingual_300m", "kind": "omnilingual", "model": "asr_omnilingual.int8.onnx", "tokens": "asr_omnilingual_tokens.txt"}],
        "vad": "silero_vad.onnx",
        "licences": {"asr": "Apache-2.0 (Meta Omnilingual ASR)", "vad": "MIT (Silero)", "voice": "CC BY-NC-SA 4.0 (derived from NII AntiDeepfake)"},
    }
    meta = VOICE / "voice.json"
    if meta.exists():
        v = json.loads(meta.read_text(encoding="utf-8"))
        files["voice.int8.onnx"] = VOICE / "voice.int8.onnx"
        manifest["voice"] = {"model": "voice.int8.onnx", "threshold": v["threshold"], "seconds": v.get("seconds", 20), "layers": v.get("layers")}
    if (CONV / "conv.fp32.onnx").exists() and (CONV / "e5base.int8.onnx").exists():
        files["conv.onnx"] = CONV / "conv.fp32.onnx"
        files["e5base.int8.onnx"] = CONV / "e5base.int8.onnx"
        manifest["conv"] = {"model": "conv.onnx", "base": "e5base.int8.onnx"}
        manifest["licences"]["conv"] = "MIT (intfloat/multilingual-e5-small); fine-tuned on ICFD-31k (research use)"
    zpath = OUT / f"{NAME}.zip"
    with zipfile.ZipFile(zpath, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for arc, src in files.items():
            z.write(src, arc)
        z.writestr("pack.json", json.dumps(manifest, indent=2))
    sha = hashlib.sha256(zpath.read_bytes()).hexdigest()
    pack = {
        "name": NAME,
        "size_mb": round(zpath.stat().st_size / 1e6),
        "sha256": sha,
        "url": f"https://github.com/{REPO}/releases/download/{TAG}/{NAME}.zip",
        "parts": ["asr", "vad"] + [k for k in ("voice", "conv") if k in manifest],
    }
    (ROOT / "models" / "pack.json").write_text(json.dumps(pack, indent=2) + "\n", encoding="utf-8")
    return pack


def release(pack: dict) -> None:
    z = OUT / f"{NAME}.zip"
    exists = subprocess.run(["gh", "release", "view", TAG, "-R", REPO], capture_output=True).returncode == 0
    if not exists:
        subprocess.run(
            [
                "gh",
                "release",
                "create",
                TAG,
                "-R",
                REPO,
                "--title",
                f"Model pack {TAG.removeprefix('models-')}",
                "--notes",
                f"The on-phone model pack ({pack['size_mb']} MB, sha256 {pack['sha256']}). Built by `python -m ml.pack_models`.",
            ],
            check=True,
        )
    subprocess.run(["gh", "release", "upload", TAG, str(z), "--clobber", "-R", REPO], check=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--release", action="store_true")
    a = ap.parse_args()
    pack = build()
    print(json.dumps(pack, indent=2))
    if a.release:
        release(pack)


if __name__ == "__main__":
    main()
