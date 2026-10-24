"""Which on-phone speech-to-text to ship: the same sherpa-onnx runtime as the Android AAR, on 4 CPU threads.

    python -m ml.eval.asr_bakeoff                 # renders the test calls once (edge-tts, needs internet), then decodes
    python -m ml.eval.asr_bakeoff --quick         # 12 calls, clean + phone line only
    python -m ml.eval.asr_bakeoff --models omnilingual_300m --check conv --out models/eval/asr_bakeoff_conv.json

Test audio: our 27 hand-written calls and the 30 adversarial calls (data/listener/adversarial.jsonl), spoken by
Microsoft's free neural voices (en-IN for English and Hinglish, hi-IN for Hindi), through three channels:
clean, a G.711 phone line, and the "speakerphone" path (played from a small loudspeaker across a room into a
phone mic, then G.711; ml/augment/telephony.py). Speech is split with Silero VAD, as on the phone.

For every model (and the Hindi+English pairs, where both texts go to the listener) it reports:
  - WER against the script, after the listener's own normalising and Devanagari folding (so "पुलिस" = "pulis"),
  - cue recall: of the cue categories the script contains, how many the recognised text still has,
  - the listener's verdict on the recognised text: scams at warn, harmless at warn / scam,
  - real-time factor (decode seconds / audio seconds) on this CPU with 4 threads.
Writes models/eval/asr_bakeoff.json (ml.eval.run_all copies it into RESULTS.md).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import time
from pathlib import Path

import numpy as np

from engine.listener.analyzer import analyze_text
from engine.listener.classifier import tokens
from engine.listener.rules import score_text
from ml import listener_data
from ml.eval.metrics import wilson

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "data" / "datasets" / "asr"
TTS = ROOT / "data" / "datasets" / "tts_calls"
OUT = ROOT / "models" / "eval" / "asr_bakeoff.json"
VOICES = {
    "en": ["en-IN-NeerjaNeural", "en-IN-PrabhatNeural"],
    "hinglish": ["en-IN-PrabhatNeural", "en-IN-NeerjaNeural"],
    "hi": ["hi-IN-SwaraNeural", "hi-IN-MadhurNeural"],
}
CANDIDATES = {
    "dolphin_base": "sherpa-onnx-dolphin-base-ctc-multi-lang-int8-2025-04-02",
    "omnilingual_300m": "sherpa-onnx-omnilingual-asr-1600-languages-300M-ctc-v2-int8-2026-02-05",
    "moonshine_tiny_en": "sherpa-onnx-moonshine-tiny-en-quantized-2026-02-27",
    "whisper_tiny": "sherpa-onnx-whisper-tiny",
    # AI4Bharat IndicConformer (Hindi) and NeMo fast-conformer (English), CTC, int8: parismitaglobalsolutions/indicconformer-sherpa-onnx
    "indicconformer_hi": "indicconformer/hi",
    "indicconformer_en": "indicconformer/en",
}
PAIRS = {
    "dolphin_base+moonshine_tiny_en": ["dolphin_base", "moonshine_tiny_en"],
    "omnilingual_300m+moonshine_tiny_en": ["omnilingual_300m", "moonshine_tiny_en"],
    "indicconformer_hi+indicconformer_en": ["indicconformer_hi", "indicconformer_en"],
}
CHANNELS = ["clean", "g711u", "ota+g711u"]


def calls() -> list[dict]:
    rows = [r for r in listener_data.load() if r["source"] in ("team_calls", "adversarial")]
    return sorted(rows, key=lambda r: r["id"])


async def _render(text: str, voice: str, path: Path) -> None:
    import edge_tts

    await edge_tts.Communicate(text, voice, rate="-5%").save(str(path))


def audio_for(r: dict, i: int) -> np.ndarray:
    import soundfile as sf

    from engine.audio.codec import resample

    TTS.mkdir(parents=True, exist_ok=True)
    path = TTS / (r["id"].replace("/", "__") + ".mp3")
    if not path.exists():
        asyncio.run(_render(r["text"], VOICES[r["lang"]][i % 2], path))
    x, sr = sf.read(str(path), dtype="float32", always_2d=False)
    if x.ndim > 1:
        x = x.mean(axis=1)
    return resample(x, sr, 16000).astype(np.float32)


def through(x: np.ndarray, ch: str, seed: int) -> np.ndarray:
    from ml.augment.telephony import channel

    return x if ch == "clean" else channel(x, ch, seed=seed, genuine=False).astype(np.float32)


def recognizer(name: str, threads: int = 4):
    import sherpa_onnx as so

    d = MODELS / CANDIDATES[name]
    tok = next(str(t) for t in (d / "tokens.txt", d.parent / "tokens.txt", *d.glob("*tokens.txt")) if t.exists())
    if name.startswith("dolphin"):
        return so.OfflineRecognizer.from_dolphin_ctc(model=str(next(d.glob("model*.onnx"))), tokens=tok, num_threads=threads)
    if name.startswith("omnilingual"):
        return so.OfflineRecognizer.from_omnilingual_asr_ctc(model=str(next(d.glob("model*.onnx"))), tokens=tok, num_threads=threads)
    if name.startswith("moonshine"):
        return so.OfflineRecognizer.from_moonshine_v2(
            encoder=str(d / "encoder_model.ort"), decoder=str(d / "decoder_model_merged.ort"), tokens=tok, num_threads=threads
        )
    if name.startswith("indicconformer"):
        return so.OfflineRecognizer.from_nemo_ctc(model=str(d / "model.int8.onnx"), tokens=tok, num_threads=threads)
    if name.startswith("whisper"):
        enc = str(next(d.glob("*encoder.int8.onnx")))
        dec = str(next(d.glob("*decoder.int8.onnx")))
        return so.OfflineRecognizer.from_whisper(encoder=enc, decoder=dec, tokens=tok, num_threads=threads, language="hi")
    raise ValueError(name)


def vad_segments(x: np.ndarray) -> list[np.ndarray]:
    import sherpa_onnx as so

    cfg = so.VadModelConfig()
    cfg.silero_vad.model = str(MODELS / "silero_vad.onnx")
    cfg.silero_vad.min_silence_duration = 0.4
    cfg.silero_vad.max_speech_duration = 12
    cfg.sample_rate = 16000
    vad = so.VoiceActivityDetector(cfg, buffer_size_in_seconds=120)
    segs = []
    for i in range(0, len(x), 512):
        vad.accept_waveform(x[i : i + 512])
        while not vad.empty():
            segs.append(np.array(vad.front.samples, dtype=np.float32))
            vad.pop()
    vad.flush()
    while not vad.empty():
        segs.append(np.array(vad.front.samples, dtype=np.float32))
        vad.pop()
    return segs or [x]


def decode_parts(rec, segs: list[np.ndarray]) -> list[str]:
    """One text per speech segment, as the phone hears a call."""
    out = []
    for s in segs:
        st = rec.create_stream()
        st.accept_waveform(16000, s)
        rec.decode_stream(st)
        out.append(st.result.text.strip())
    return [t for t in out if t]


def decode(rec, segs: list[np.ndarray]) -> str:
    return " ".join(decode_parts(rec, segs))


def wer(ref: str, hyp: str) -> tuple[int, int]:
    """Word edits and reference length, on the listener's own tokens (Devanagari folded)."""
    r, h = tokens(ref), tokens(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev, d[j] = d[j], cur
    return d[len(h)], len(r)


def rate(k: int, n: int) -> dict:
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "rate": round(k / n, 4) if n else None, "ci95": [round(lo, 4), round(hi, 4)]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--models", nargs="*", default=list(CANDIDATES))
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--check", choices=["basic", "conv"], default="basic", help="conv: the conversation check, fed segment by segment")
    a = ap.parse_args()
    rows = calls()
    chans = CHANNELS
    if a.quick:
        rows = random.Random(0).sample(rows, 12)
        chans = ["clean", "g711u"]
    print(f"{len(rows)} calls × {len(chans)} channels", flush=True)
    audio = {r["id"]: audio_for(r, i) for i, r in enumerate(rows)}
    segs = {(r["id"], ch): vad_segments(through(audio[r["id"]], ch, seed=k)) for k, r in enumerate(rows) for ch in chans}
    secs = {r["id"]: len(audio[r["id"]]) / 16000 for r in rows}
    hyps: dict[str, dict] = {}
    parts: dict[str, dict] = {}
    timing: dict[str, float] = {}
    for m in a.models:
        rec = recognizer(m)
        t0 = time.time()
        parts[m] = {f"{rid}|{ch}": decode_parts(rec, s) for (rid, ch), s in segs.items()}
        hyps[m] = {k: " ".join(v) for k, v in parts[m].items()}
        timing[m] = (time.time() - t0) / (sum(secs.values()) * len(chans))
        print(f"{m}: RTF {timing[m]:.3f}", flush=True)
    for p, pair in PAIRS.items():
        if all(x in hyps for x in pair):
            hyps[p] = {k: " ".join(hyps[x][k] for x in pair) for k in hyps[pair[0]]}
            parts[p] = {k: [t for x in pair for t in parts[x][k]] for k in hyps[pair[0]]}
            timing[p] = sum(timing[x] for x in pair)
    res: dict = {"check": a.check, "calls": len(rows), "channels": chans, "seconds_of_audio": round(sum(secs.values()), 1), "models": {}}
    for m, hs in hyps.items():
        per = {}
        for ch in chans:
            edits = refs = cue_hit = cue_all = 0
            lv = []
            for r in rows:
                h = hs[f"{r['id']}|{ch}"]
                if "+" not in m:
                    e, n = wer(r["text"], h)
                    edits, refs = edits + e, refs + n
                want = set(score_text(r["text"]).categories) - {"discussion"}
                got = set(score_text(h).categories)
                cue_all += len(want)
                cue_hit += len(want & got)
                if a.check == "conv":
                    from engine.listener.conversation import analyze

                    lv.append((r["label"], analyze(parts[m][f"{r['id']}|{ch}"]).level))
                else:
                    lv.append((r["label"], analyze_text(h, min_words=12).level))
            pos = [x for y, x in lv if y == 1]
            neg = [x for y, x in lv if y == 0]
            per[ch] = {
                "wer": round(edits / refs, 4) if refs else None,
                "cue_recall": rate(cue_hit, cue_all),
                "scams_at_warn": rate(sum(x in ("warn", "scam") for x in pos), len(pos)),
                "harmless_at_warn": rate(sum(x in ("warn", "scam") for x in neg), len(neg)),
                "harmless_at_scam": rate(sum(x == "scam" for x in neg), len(neg)),
            }
        res["models"][m] = {"rtf_4_threads": round(timing[m], 3), "size_mb": _size(m), "channels": per}
    res["examples"] = {m: dict(list(hs.items())[:6]) for m, hs in hyps.items()}
    res["markdown"] = markdown(res)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(res["markdown"])
    return 0


def _size(m: str) -> int:
    parts = PAIRS.get(m, [m])
    return int(sum(f.stat().st_size for p in parts for f in (MODELS / CANDIDATES[p]).glob("*") if f.is_file()) / 1e6)


def markdown(res: dict) -> str:
    L = [
        f"{res['calls']} calls ({res['seconds_of_audio']} s each channel), spoken by en-IN / hi-IN neural voices; WER on the listener's folded tokens.",
        "",
        "| Model | MB | RTF (4 threads, laptop) | Channel | WER | Cue recall | Scams at warn | Harmless at warn | Harmless at scam |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for m, d in res["models"].items():
        for ch, p in d["channels"].items():
            w = "–" if p["wer"] is None else f"{100 * p['wer']:.0f}%"
            f = lambda x: f"{100 * x['rate']:.0f}% ({x['k']}/{x['n']})" if x["n"] else "–"  # noqa: E731
            L.append(
                f"| {m} | {d['size_mb']} | {d['rtf_4_threads']} | {ch} | {w} | {f(p['cue_recall'])} | {f(p['scams_at_warn'])} | {f(p['harmless_at_warn'])} | {f(p['harmless_at_scam'])} |"
            )
    return "\n".join(L)


if __name__ == "__main__":
    raise SystemExit(main())
