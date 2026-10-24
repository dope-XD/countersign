"""Stock AI voices: the fakes a judge can download in a minute, without cloning anyone.

    python -m ml.tts_sets                       # every generator that is installed / has a key
    python -m ml.tts_sets edge gtts downloads   # only some
    python -m ml.tts_sets --genuine 600         # also add held-out genuine clips (default 600)

Generators (each skipped with a note if it can't run):
  edge       Microsoft Azure neural voices through edge-tts (en-IN, hi-IN, a few multilingual)
  gtts       Google Translate TTS through gTTS (Indian, US and UK English; Hindi)
  piper      open VITS voices run locally (piper-tts; hi_IN and English voices from rhasspy/piper-voices)
  kokoro     Kokoro-82M run locally, if the `kokoro` package is installed
  elevenlabs ElevenLabs premade voices, when ELEVENLABS_API_KEY is set (eleven_multilingual_v2)
  mlaad      the MLAAD systems fetched by `python -m ml.fetch_data mlaad_wide` (gated; commercial
             products such as ElevenLabs v3, OpenAI TTS-1 HD, Gemini, Cartesia, and open models)
  downloads  files you saved yourself in data/ai_downloads/, listed in data/ai_downloads/labels.csv
             with columns file,generator,source_url,licence[,language,voice]

Writes data/clips/tts_stock/<generator>/*.flac (16 kHz, silence trimmed, at most 6 s per clip)
and data/manifests/tts_stock.csv in the build_manifest format (path,label,speaker,language,
generator,source,split). `speaker` is the voice, `generator` the product or model, and every
row's split is "eval": none of these generators is in train.csv, so the calibration never sees
them. The genuine rows are dev-split FLEURS Hindi and In-the-Wild English, also held out.

    python -m ml.eval.benchmark --manifest data/manifests/tts_stock.csv --name "Stock AI voices" \
        --channels clean,g711u,ota+g711u,ota+amrnb_12k2,ota+g711u+noise
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import os
import random
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from engine.audio.codec import resample
from ml.augment.telephony import load_audio
from ml.build_manifest import FIELDS, MAN, MAX_S
from ml.s1_data import read

ROOT = Path(__file__).resolve().parent.parent
CLIPS = ROOT / "data" / "clips" / "tts_stock"
DOWNLOADS = ROOT / "data" / "ai_downloads"
SR = 16000

# What a caller says to a bank: short, plain, with account words and numbers
TEXT_EN = [
    "Hello, I am calling about my savings account. I need to update my registered mobile number today.",
    "Good morning. My debit card was blocked yesterday and I want to get it unblocked as soon as possible.",
    "Hi, this is regarding a transfer of fifty thousand rupees that I made to my brother's account this morning.",
    "I have changed my phone, so please link my new number to the account. The old SIM is not working.",
    "Can you please increase my daily UPI limit? I have an urgent payment to make to a hospital.",
    "My date of birth is the fourteenth of March, nineteen eighty six, and my customer ID ends in four two seven.",
    "Yes, I can confirm the last three transactions. Please go ahead and add the new beneficiary.",
    "I am travelling right now and I cannot visit the branch, so I need this done over the phone.",
    "Please send the one time password to my email instead, I am not getting the SMS on my phone.",
    "Actually, my wife usually handles this, but she is not available. I am the joint account holder.",
    "I want to close my fixed deposit early and move the money to my current account.",
    "Why was my net banking locked? I only entered the password wrong once, I am quite sure.",
]
TEXT_HI = [
    "नमस्ते, मैं अपने बचत खाते के बारे में बात करना चाहता हूँ। मुझे अपना मोबाइल नंबर बदलवाना है।",
    "मेरा डेबिट कार्ड कल ब्लॉक हो गया था, कृपया उसे जल्दी से चालू कर दीजिए।",
    "आज सुबह मैंने अपने भाई के खाते में पचास हज़ार रुपये भेजे थे, उसी के बारे में फ़ोन किया है।",
    "मैंने नया फ़ोन लिया है, कृपया मेरा नया नंबर खाते से जोड़ दीजिए। पुराना सिम काम नहीं कर रहा।",
    "क्या आप मेरी यूपीआई की रोज़ की सीमा बढ़ा सकते हैं? मुझे अस्पताल में तुरंत पैसे भरने हैं।",
    "मेरी जन्म तिथि चौदह मार्च उन्नीस सौ छियासी है, और ग्राहक आईडी के आख़िरी अंक चार दो सात हैं।",
    "हाँ, पिछले तीन लेन-देन सही हैं। आप नया लाभार्थी जोड़ दीजिए।",
    "मैं अभी यात्रा कर रहा हूँ, शाखा नहीं आ सकता, इसलिए यह काम फ़ोन पर ही करवाना है।",
    "ओटीपी मेरे ईमेल पर भेज दीजिए, फ़ोन पर एसएमएस नहीं आ रहा है।",
    "मुझे अपनी फ़िक्स्ड डिपॉज़िट समय से पहले तोड़कर पैसे चालू खाते में डालने हैं।",
]
TEXT_HINGLISH = [
    "Hello ji, mera account number change karna hai, naya mobile number link kar dijiye please.",
    "Mera card block ho gaya hai, aur mujhe abhi urgent payment karni hai, please jaldi kijiye.",
    "Maine subah pachaas hazaar transfer kiye the, woh abhi tak credit nahi hua hai.",
    "OTP nahi aa raha hai, aap email pe bhej dijiye na, main abhi travel kar raha hoon.",
]

EDGE_VOICES = {  # voice -> language of the texts it reads
    "en-IN-NeerjaNeural": "en",
    "en-IN-NeerjaExpressiveNeural": "en",
    "en-IN-PrabhatNeural": "en",
    "hi-IN-SwaraNeural": "hi",
    "hi-IN-MadhurNeural": "hi",
    "en-US-AvaMultilingualNeural": "en",
    "en-US-AndrewMultilingualNeural": "en",
    "en-US-EmmaMultilingualNeural": "en",
}
GTTS_VOICES = {"en-co.in": ("en", "co.in"), "en-com": ("en", "com"), "en-co.uk": ("en", "co.uk"), "hi-co.in": ("hi", "co.in")}
PIPER_VOICES = [
    "hi/hi_IN/pratham/medium/hi_IN-pratham-medium",
    "hi/hi_IN/priyamvada/medium/hi_IN-priyamvada-medium",
    "hi/hi_IN/rohan/medium/hi_IN-rohan-medium",
    "en/en_US/l2arctic/medium/en_US-l2arctic-medium",
    "en/en_US/kusal/medium/en_US-kusal-medium",
    "en/en_GB/alan/medium/en_GB-alan-medium",
    "en/en_US/lessac/high/en_US-lessac-high",
    "en/en_US/ryan/high/en_US-ryan-high",
]
KOKORO_VOICES = {"af_heart": ("a", "en"), "am_michael": ("a", "en"), "bf_emma": ("b", "en"), "hf_alpha": ("h", "hi"), "hm_omega": ("h", "hi")}

# Commercial products a judge would download from vs open models anyone can run
COMMERCIAL = (
    "edge-tts", "gtts", "elevenlabs", "openai", "google", "gemini", "microsoft-azure", "azure", "sarvam", "playht", "murf",
    "resemble", "polly", "amazon", "cartesia", "deepgram", "minimax", "inworld", "rime", "smallest", "ringg",
)  # fmt: skip


def family(generator: str) -> str:
    """'commercial' for hosted TTS products, 'open' for open-source TTS and voice clones,
    'unknown' when the set doesn't say (In-the-Wild)."""
    g = generator.lower()
    if g in ("", "unknown"):
        return "unknown"
    return "commercial" if g.startswith(COMMERCIAL) else "open"


def texts(lang: str) -> list[str]:
    return TEXT_HI if lang == "hi" else TEXT_EN + TEXT_HINGLISH


def trim(x: np.ndarray, thresh_db: float = -40) -> np.ndarray:
    """Cut leading and trailing silence (20 ms frames more than 40 dB under the loudest)."""
    f = 320
    n = len(x) // f
    if n == 0:
        return x
    e = 10 * np.log10(np.mean(x[: n * f].reshape(n, f) ** 2, axis=1) + 1e-12)
    on = np.flatnonzero(e > e.max() + thresh_db)
    if not len(on):
        return x
    return x[max(0, (on[0] - 2) * f) : min(len(x), (on[-1] + 3) * f)]


def rel(p: Path) -> str:
    return str(p.relative_to(ROOT)).replace("\\", "/")


def save(gen: str, key: str, x: np.ndarray) -> str | None:
    """Write one clip; None if it is too short to score (under 1 s of speech)."""
    x = trim(x.astype(np.float32))[: int(MAX_S * SR)]
    if len(x) < SR:
        return None
    d = CLIPS / gen
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{re.sub(r'[^A-Za-z0-9_.-]+', '_', key)}.flac"
    sf.write(p, x / (np.max(np.abs(x)) + 1e-9) * 0.9, SR, format="FLAC", subtype="PCM_16")
    return rel(p)


def decode(data: bytes, suffix: str) -> np.ndarray:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / f"a{suffix}"
        p.write_bytes(data)
        return load_audio(str(p))


def row(path: str, voice: str, lang: str, gen: str, source: str = "tts_stock") -> dict:
    return {"path": path, "label": "spoof", "speaker": voice, "language": lang, "generator": gen, "source": source, "split": "eval"}


# ------------------------------------------------------------------ generators
def edge(per_voice: int) -> list[dict]:
    import edge_tts

    async def one(voice: str, text: str) -> bytes:
        buf = io.BytesIO()
        async for chunk in edge_tts.Communicate(text, voice).stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
        return buf.getvalue()

    out = []
    for voice, lang in EDGE_VOICES.items():
        for i, t in enumerate(texts(lang)[:per_voice]):
            key = f"{voice}_{i}"
            p = CLIPS / "edge-tts" / f"{key}.flac"
            try:
                path = rel(p) if p.exists() else save("edge-tts", key, decode(asyncio.run(one(voice, t)), ".mp3"))
            except Exception as e:  # the service sometimes returns nothing for one request
                print(f"  edge-tts {key}: {type(e).__name__}")
                continue
            if path:
                out.append(row(path, voice, lang, "edge-tts"))
    return out


def gtts(per_voice: int) -> list[dict]:
    from gtts import gTTS

    out = []
    for voice, (lang, tld) in GTTS_VOICES.items():
        for i, t in enumerate(texts(lang)[:per_voice]):
            key = f"{voice}_{i}"
            p = CLIPS / "gtts" / f"{key}.flac"
            if p.exists():
                path = rel(p)
            else:
                buf = io.BytesIO()
                gTTS(t, lang=lang, tld=tld).write_to_fp(buf)
                path = save("gtts", key, decode(buf.getvalue(), ".mp3"))
            if path:
                out.append(row(path, voice, lang, "gtts"))
    return out


PIPER_WORKER = """
import json, sys, wave
from huggingface_hub import hf_hub_download
from piper import PiperVoice
voice, out, texts = sys.argv[1], sys.argv[2], json.loads(sys.stdin.read())
onnx = hf_hub_download("rhasspy/piper-voices", voice + ".onnx")
hf_hub_download("rhasspy/piper-voices", voice + ".onnx.json")
v = PiperVoice.load(onnx)
for i, t in enumerate(texts):
    with wave.open(f"{out}/{i}.wav", "wb") as w:
        v.synthesize_wav(t, w)
"""


def piper(per_voice: int) -> list[dict]:
    """Piper runs in its own process: its onnxruntime crashes on Windows when torch is already loaded."""
    out = []
    for v in PIPER_VOICES:
        name = v.rsplit("/", 1)[1]
        lang = "hi" if name.startswith("hi_") else "en"
        todo = texts(lang)[:per_voice]
        with tempfile.TemporaryDirectory() as d:
            subprocess.run([sys.executable, "-c", PIPER_WORKER, v, d], input=json.dumps(todo), text=True, encoding="utf-8", check=True)
            for i in range(len(todo)):
                path = save("piper", f"{name}_{i}", load_audio(f"{d}/{i}.wav"))
                if path:
                    out.append(row(path, name, lang, "piper-vits"))
    return out


def kokoro(per_voice: int) -> list[dict]:
    from kokoro import KPipeline

    out = []
    pipes: dict = {}
    for voice, (code, lang) in KOKORO_VOICES.items():
        pipe = pipes.setdefault(code, KPipeline(lang_code=code))
        for i, t in enumerate(texts(lang)[:per_voice]):
            audio = np.concatenate([np.asarray(a, dtype=np.float32) for _, _, a in pipe(t, voice=voice)])
            path = save("kokoro", f"{voice}_{i}", resample(audio, 24000, SR))
            if path:
                out.append(row(path, voice, lang, "kokoro"))
    return out


def elevenlabs(per_voice: int, n_voices: int = 8) -> list[dict]:
    import requests

    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        raise RuntimeError("ELEVENLABS_API_KEY is not set")
    h = {"xi-api-key": key}
    voices = requests.get("https://api.elevenlabs.io/v1/voices", headers=h, timeout=30).json()["voices"]
    voices = [v for v in voices if v.get("category") == "premade"][:n_voices]
    out = []
    for v in voices:
        for lang in ("en", "hi"):
            for i, t in enumerate(texts(lang)[: max(1, per_voice // 2)]):
                key_ = f"{v['name']}_{lang}{i}"
                p = CLIPS / "elevenlabs" / f"{re.sub(r'[^A-Za-z0-9_.-]+', '_', key_)}.flac"
                if p.exists():
                    path = rel(p)
                else:
                    r = requests.post(
                        f"https://api.elevenlabs.io/v1/text-to-speech/{v['voice_id']}?output_format=mp3_44100_128",
                        headers=h,
                        json={"text": t, "model_id": "eleven_multilingual_v2"},
                        timeout=60,
                    )
                    r.raise_for_status()
                    path = save("elevenlabs", key_, decode(r.content, ".mp3"))
                if path:
                    out.append(row(path, v["name"], lang, "elevenlabs"))
    return out


def mlaad(per_voice: int) -> list[dict]:
    """MLAAD clips from data/datasets/mlaad_wide/fake/<lang>/<system>/ (see ml/fetch_data.py)."""
    base = ROOT / "data" / "datasets" / "mlaad_wide" / "fake"
    files = sorted(f for f in base.glob("*/*/*") if f.suffix in (".wav", ".mp3", ".flac"))
    if not files:
        raise RuntimeError("nothing in data/datasets/mlaad_wide; run `python -m ml.fetch_data mlaad_wide` (gated: accept the terms, huggingface-cli login)")
    out = []
    for f in files:
        lang, system = f.parent.parent.name, f.parent.name
        slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", system)
        p = CLIPS / f"mlaad_{slug}" / f"{f.stem}.flac"
        path = rel(p) if p.exists() else save(f"mlaad_{slug}", f.stem, load_audio(str(f)))
        if path:
            out.append(row(path, system, lang, system, source="mlaad"))
    return out


def downloads(max_segments: int = 3) -> list[dict]:
    """Files a person downloaded from TTS demo pages and listed in data/ai_downloads/labels.csv.
    A long file gives up to `max_segments` non-overlapping 6 s clips, all with the file as the
    speaker, so a split by speaker keeps them together."""
    labels = DOWNLOADS / "labels.csv"
    if not labels.exists():
        raise RuntimeError(f"no {labels.relative_to(ROOT)} (columns: file,generator,source_url,licence[,language,voice])")
    out = []
    for r in read(labels):
        f = DOWNLOADS / r["file"]
        if not f.exists():
            print(f"  missing {f.relative_to(ROOT)}, skipped")
            continue
        x = trim(load_audio(str(f)))
        gen = r["generator"].strip().lower()
        seg = int(MAX_S * SR)
        for k in range(min(max_segments, max(1, len(x) // seg))):
            path = save(f"downloads_{gen}", f"{f.stem}_{k}", x[k * seg : (k + 1) * seg])
            if path:
                out.append(row(path, r.get("voice") or f.stem, r.get("language") or "en", gen, source="ai_downloads"))
    return out


GENERATORS = {"edge": edge, "gtts": gtts, "piper": piper, "kokoro": kokoro, "elevenlabs": elevenlabs, "mlaad": mlaad, "downloads": downloads}
LABEL = {"edge": "edge-tts", "gtts": "gtts", "piper": "piper-vits", "kokoro": "kokoro", "elevenlabs": "elevenlabs"}


def runner(r: dict) -> str | None:
    """Which generator function produced a manifest row (None for genuine rows)."""
    if r["label"] == "bonafide":
        return None
    if r["source"] == "ai_downloads":
        return "downloads"
    if r["source"] == "mlaad":
        return "mlaad"
    return next((k for k, v in LABEL.items() if v == r["generator"]), None)


def genuine(n: int, seed: int = 0) -> list[dict]:
    """Held-out real speech to pair with the fakes: dev-split FLEURS Hindi and In-the-Wild English."""
    rng = random.Random(seed)
    pools = []
    if (MAN / "dev.csv").exists():
        pools.append([r for r in read(MAN / "dev.csv") if r["label"] == "bonafide" and r["source"] == "fleurs_hi"])
    if (MAN / "itw.csv").exists():
        pools.append([r for r in read(MAN / "itw.csv") if r["label"] == "bonafide"])
    out = []
    for pool in pools:
        out += rng.sample(pool, min(len(pool), n // max(1, len(pools))))
    return [{**{k: r.get(k, "") for k in FIELDS}, "split": "eval"} for r in out]


def write(rows: list[dict], name: str = "tts_stock") -> Path:
    MAN.mkdir(parents=True, exist_ok=True)
    p = MAN / f"{name}.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        w.writerows(rows)
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("only", nargs="*", help=f"generators to run: {', '.join(GENERATORS)}")
    ap.add_argument("--per-voice", type=int, default=12)
    ap.add_argument("--genuine", type=int, default=600)
    a = ap.parse_args()
    ran = a.only or list(GENERATORS)
    old = MAN / "tts_stock.csv"
    # rows from generators not run this time stay, so `python -m ml.tts_sets downloads` only adds files
    rows = [r for r in read(old) if runner(r) and runner(r) not in ran] if old.exists() else []
    for name in ran:
        try:
            got = GENERATORS[name](a.per_voice) if name != "downloads" else downloads()
            print(f"{name}: {len(got)} clips")
            rows += got
        except Exception as e:  # a missing package, key or network shouldn't stop the others
            print(f"{name}: skipped ({type(e).__name__}: {e})")
    rows += genuine(a.genuine)
    p = write(rows)
    by_gen: dict[str, int] = {}
    for r in rows:
        by_gen[r["generator"] or "-"] = by_gen.get(r["generator"] or "-", 0) + 1
    print(f"wrote {p.relative_to(ROOT)}: {len(rows)} rows", by_gen)


if __name__ == "__main__":
    main()
