"""Build the spot-check kit in data/kit/: 30 items from public held-out data, and expected.csv.

    python -m ml.eval.make_kit          # needs internet once (edge-tts voices, FLEURS clips via ml.fetch_data)

Items (never trained or tuned on):
  - 10 texts: scam and harmless messages and call lines from the india14 test suite, the Hinglish call set's test split
    and BothBosu's test file (Apache-2.0 / MIT).
  - 10 call recordings: held-out scam and harmless call scripts from the same public test sets, spoken by Microsoft's
    en-IN / hi-IN neural voices and passed through a G.711 phone line (ml/augment/telephony.py).
  - 10 voices: 5 real people (FLEURS Hindi test, CC BY 4.0) and 5 AI voices (edge-tts reading FLEURS sentences).
expected.csv: file, kind (text | call | voice), expect (scam | harmless | ai | real), source, licence.
A call or text passes when a scam reaches at least the amber card and a harmless one stays below it; a voice passes when
the voice-clone check says AI for AI and real for real. The same files work on the phone's "Check a recording" screen.
"""

from __future__ import annotations

import asyncio
import csv
import io
import random
from pathlib import Path

import numpy as np

from ml import listener_data

ROOT = Path(__file__).resolve().parents[2]
KIT = ROOT / "data" / "kit"
SEED = 24


def _tts(text: str, voice: str, path: Path) -> None:
    import edge_tts

    async def go() -> None:
        await edge_tts.Communicate(text, voice, rate="-5%").save(str(path))

    asyncio.run(go())


def _to_phone_wav(mp3: Path, wav: Path, seed: int) -> None:
    import soundfile as sf

    from engine.audio.codec import resample
    from ml.augment.telephony import channel

    x, sr = sf.read(str(mp3), dtype="float32", always_2d=False)
    x = x.mean(axis=1) if x.ndim > 1 else x
    y = channel(resample(x, sr, 16000).astype(np.float32), "g711u", seed=seed)
    sf.write(str(wav), np.clip(y, -1, 1), 16000, subtype="PCM_16")
    mp3.unlink()


def _fleurs_hi(n: int, rng: random.Random) -> list[tuple[np.ndarray, str]]:
    """Real speech: FLEURS Hindi clips (validation split; the voice model trains on FLEURS train only)."""
    import pyarrow.parquet as pq
    import soundfile as sf

    from engine.audio.codec import resample

    files = sorted((ROOT / "data" / "datasets" / "fleurs_hi").rglob("validation-*.parquet"))
    t = pq.read_table(files[0]).to_pylist()
    rng.shuffle(t)
    out = []
    for r in t[:n]:
        a = r["audio"]
        x, sr = sf.read(io.BytesIO(a["bytes"]), dtype="float32", always_2d=False)
        out.append((resample(x, sr, 16000).astype(np.float32), r.get("transcription") or r.get("raw_transcription") or ""))
    return out


def main() -> None:
    import soundfile as sf

    KIT.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    rows = [r for r in listener_data.load(with_ours=False) if r["split"] == "test"]
    pick = lambda src, label, k, maxw=120: rng.sample([r for r in rows if r["source"] == src and r["label"] == label and len(r["text"].split()) <= maxw], k)  # noqa: E731
    out = []
    # 10 texts
    texts = pick("india_sms", 1, 3) + pick("india_sms", 0, 2) + pick("hinglish_calls", 1, 2) + pick("hinglish_calls", 0, 1) + pick("bothbosu", 1, 1) + pick("bothbosu", 0, 1)
    for i, r in enumerate(texts, 1):
        f = f"text_{i:02d}.txt"
        (KIT / f).write_text(r["text"] + "\n", encoding="utf-8")
        out.append({"file": f, "kind": "text", "expect": "scam" if r["label"] else "harmless", "source": r["id"], "licence": "MIT" if r["source"] == "india_sms" else "Apache-2.0"})
    # 10 calls: Hinglish and BothBosu test scripts, spoken, over a phone line
    calls = pick("hinglish_calls", 1, 3) + pick("hinglish_calls", 0, 2) + pick("bothbosu", 1, 3, 160) + pick("bothbosu", 0, 2, 160)
    for i, r in enumerate(calls, 1):
        f = f"call_{i:02d}.wav"
        text = listener_data.re.sub(r"\b(caller|receiver)\s*:", "", r["text"], flags=listener_data.re.I)
        mp3 = KIT / f"call_{i:02d}.mp3"
        _tts(text, ["en-IN-PrabhatNeural", "en-IN-NeerjaNeural"][i % 2], mp3)
        _to_phone_wav(mp3, KIT / f, seed=i)
        out.append({"file": f, "kind": "call", "expect": "scam" if r["label"] else "harmless", "source": r["id"] + " (spoken by edge-tts, G.711)", "licence": "Apache-2.0 text"})
    # 10 voices: 5 real (FLEURS hi validation), 5 AI (edge-tts reading other FLEURS sentences)
    real = _fleurs_hi(10, rng)
    for i, (x, _) in enumerate(real[:5], 1):
        f = f"voice_real_{i:02d}.wav"
        sf.write(str(KIT / f), x, 16000, subtype="PCM_16")
        out.append({"file": f, "kind": "voice", "expect": "real", "source": "google/fleurs hi_in validation", "licence": "CC BY 4.0"})
    for i, (_, sentence) in enumerate(real[5:], 1):
        f = f"voice_ai_{i:02d}.wav"
        mp3 = KIT / f"voice_ai_{i:02d}.mp3"
        _tts(sentence, ["hi-IN-SwaraNeural", "hi-IN-MadhurNeural"][i % 2], mp3)
        x, sr = sf.read(str(mp3), dtype="float32", always_2d=False)
        from engine.audio.codec import resample

        sf.write(str(KIT / f), resample(x if x.ndim == 1 else x.mean(axis=1), sr, 16000), 16000, subtype="PCM_16")
        mp3.unlink()
        out.append({"file": f, "kind": "voice", "expect": "ai", "source": "edge-tts hi-IN reading a FLEURS sentence", "licence": "generated"})
    with open(KIT / "expected.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["file", "kind", "expect", "source", "licence"])
        w.writeheader()
        w.writerows(out)
    print(f"wrote {len(out)} items to {KIT}")


if __name__ == "__main__":
    main()
