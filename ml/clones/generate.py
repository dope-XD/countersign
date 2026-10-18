"""Make consented clones of teammates' voices for the IndiaCall attack set.

Runs in the separate clones environment (see docs/CLONES.md), not the engine venv:

    .venv-clones/Scripts/python -m ml.clones.generate xtts --speakers pushkar sarah reshaan
    .venv-clones/Scripts/python -m ml.clones.generate seedvc --speakers pushkar sarah reshaan

Outputs go to data/indiacall/clones/<generator>/<speaker>/<item>.wav, each folder with a
SYNTHETIC label file. Only speakers with a consent record are cloned. Clone files are
never released and are deleted after the event (python -m ml.clones.generate purge).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from engine.indiacall import OPENINGS, PASSAGES, VOICE_NOTES, challenges  # noqa: E402

IC = ROOT / "data" / "indiacall"
REC = IC / "recordings"
OUT = IC / "clones"
LABEL = "SYNTHETIC SPEECH. Generated for Countersign's IndiaCall test at RAKSHAM 2026 from consented teammates. Not for release. Delete after the event.\n"

PASSAGE_TEXT = {pid: text for pid, _l, text in PASSAGES}


def texts() -> list[tuple[str, str, str]]:
    """(item id, language, text) for everything a clone has to say."""
    out = list(OPENINGS)
    for c in challenges().values():
        out.append((c.id, "any", c.say.split(": ", 1)[1].strip('"')))
    out += [p for p in PASSAGES if p[1] != "any"]
    out += list(VOICE_NOTES)
    return out


def check_consent(speaker: str) -> None:
    if not (IC / "consent" / f"{speaker}.json").exists():
        raise SystemExit(f"No consent record for {speaker}; refusing to clone.")


def reference(speaker: str, prefer: tuple[str, ...] = ("P01", "P03", "P02", "P04")) -> tuple[Path, str]:
    for pid in prefer:
        p = REC / speaker / f"{pid}.wav"
        if p.exists():
            return p, PASSAGE_TEXT.get(pid, "")
    raise SystemExit(f"{speaker} has no passage recordings to clone from")


def out_dir(gen: str, speaker: str) -> Path:
    d = OUT / gen / speaker
    d.mkdir(parents=True, exist_ok=True)
    (OUT / gen / "SYNTHETIC_LABEL.txt").write_text(LABEL)
    return d


def save(path: Path, wav: np.ndarray, sr: int) -> None:
    wav = np.asarray(wav, dtype=np.float32).squeeze()
    sf.write(path, wav / (np.max(np.abs(wav)) + 1e-9) * 0.9, sr)


# ----------------------------------------------------------------------------- generators
def gen_xtts(speakers: list[str]) -> None:
    from TTS.api import TTS

    tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to("cuda")
    for s in speakers:
        ref, _ = reference(s)
        d = out_dir("xtts", s)
        for item, lang, text in texts():
            tts.tts_to_file(text=text, speaker_wav=str(ref), language="hi" if lang == "hi" else "en", file_path=str(d / f"{item}.wav"))
        print("xtts", s, "done")


def gen_f5(speakers: list[str]) -> None:
    from f5_tts.api import F5TTS

    f5 = F5TTS()
    for s in speakers:
        ref, ref_text = reference(s, ("P01", "P04"))
        d = out_dir("f5", s)
        for item, lang, text in texts():
            if lang == "hi":
                continue  # the base F5 checkpoint is English/Chinese; Hindi comes from IndicF5
            f5.infer(ref_file=str(ref), ref_text=ref_text, gen_text=text, file_wave=str(d / f"{item}.wav"))
        print("f5", s, "done")


def gen_indicf5(speakers: list[str]) -> None:
    from transformers import AutoModel

    model = AutoModel.from_pretrained("ai4bharat/IndicF5", trust_remote_code=True)
    for s in speakers:
        ref, ref_text = reference(s, ("P02",))
        d = out_dir("indicf5", s)
        for item, lang, text in texts():
            if lang != "hi" and item not in challenges():
                continue
            audio = model(text, ref_audio_path=str(ref), ref_text=ref_text)
            audio = np.asarray(audio, dtype=np.float32)
            if audio.dtype == np.int16 or np.max(np.abs(audio)) > 1.5:
                audio = audio / 32768.0
            save(d / f"{item}.wav", audio, 24000)
        print("indicf5", s, "done")


def gen_chatterbox(speakers: list[str]) -> None:
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS

    m = ChatterboxMultilingualTTS.from_pretrained(device="cuda")
    for s in speakers:
        ref, _ = reference(s)
        d = out_dir("chatterbox", s)
        for item, lang, text in texts():
            wav = m.generate(text, language_id="hi" if lang == "hi" else "en", audio_prompt_path=str(ref))
            save(d / f"{item}.wav", wav.cpu().numpy(), m.sr)
        print("chatterbox", s, "done")


def gen_seedvc(speakers: list[str], seedvc_dir: str) -> None:
    """L3/L4: another teammate (the 'attacker') says each line; Seed-VC turns it into the victim's voice."""
    import subprocess

    for victim in speakers:
        ref, _ = reference(victim)
        attackers = [a for a in sorted(p.name for p in REC.iterdir() if p.is_dir()) if a != victim]
        if not attackers:
            raise SystemExit("Seed-VC needs at least two speakers")
        d = out_dir("seedvc", victim)
        tmp = d / "_tmp"
        tmp.mkdir(exist_ok=True)
        for k, (item, _lang, _text) in enumerate(texts()):
            attacker = attackers[k % len(attackers)]
            src = REC / attacker / f"{item}.wav"
            if not src.exists():
                continue
            subprocess.run(
                [
                    sys.executable,
                    "inference.py",
                    "--source",
                    str(src),
                    "--target",
                    str(ref),
                    "--output",
                    str(tmp),
                    "--diffusion-steps",
                    "30",
                    "--length-adjust",
                    "1.0",
                    "--inference-cfg-rate",
                    "0.7",
                    "--f0-condition",
                    "False",
                ],
                cwd=seedvc_dir,
                check=True,
            )
            produced = max(tmp.glob("*.wav"), key=lambda p: p.stat().st_mtime)
            shutil.move(produced, d / f"{item}.wav")
            (d / f"{item}.json").write_text(json.dumps({"attacker": attacker, "victim": victim}))
        shutil.rmtree(tmp, ignore_errors=True)
        print("seedvc", victim, "done")


def purge() -> None:
    shutil.rmtree(OUT, ignore_errors=True)
    print("deleted all clone audio")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("generator", choices=["xtts", "f5", "indicf5", "chatterbox", "seedvc", "purge"])
    ap.add_argument("--speakers", nargs="*", default=None)
    ap.add_argument("--seedvc-dir", default=str(ROOT.parent / "seed-vc"))
    a = ap.parse_args()
    if a.generator == "purge":
        purge()
        sys.exit(0)
    spk = a.speakers or sorted(p.name for p in REC.iterdir() if p.is_dir())
    for s in spk:
        check_consent(s)
    {"xtts": gen_xtts, "f5": gen_f5, "indicf5": gen_indicf5, "chatterbox": gen_chatterbox}.get(a.generator, lambda s: gen_seedvc(s, a.seedvc_dir))(spk)
