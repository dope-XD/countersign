"""The virtual agent's ears and mouth.

Mouth: ElevenLabs text-to-speech, streamed as 8 kHz mu-law (the phone line's own format), so its
frames go straight to the caller and onto the call's agent track. Without a key, or when the
service fails, the agent's line is sent as text and the caller's phone reads it out itself.

Ears: one caller utterance at a time. ElevenLabs Scribe when configured, else faster-whisper on
our own GPU (COUNTERSIGN_STT=local keeps caller audio on our server, the production default).
The transcript is used for the conversation and never stored.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator

import httpx
import numpy as np

from engine.config import settings
from engine.signals import s3_liveness

log = logging.getLogger(__name__)

ELEVEN = "https://api.elevenlabs.io/v1"
DEFAULT_VOICE = "21m00Tcm4TlvDq8ikWAM"  # used only when TTS_VOICE isn't set
FRAME = 160  # 20 ms of 8 kHz mu-law
_http: httpx.AsyncClient | None = None


def _client() -> httpx.AsyncClient:
    global _http
    if _http is None:
        _http = httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0))
    return _http


def tts_available() -> bool:
    return bool(settings.elevenlabs_key)


async def speak(text: str) -> AsyncIterator[bytes]:
    """The line as 20 ms mu-law frames, as fast as ElevenLabs makes them. Raises on failure."""
    url = f"{ELEVEN}/text-to-speech/{settings.tts_voice or DEFAULT_VOICE}/stream"
    body = {"text": text, "model_id": settings.tts_model, "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}}
    buf = b""
    async with _client().stream("POST", url, params={"output_format": "ulaw_8000"}, json=body, headers={"xi-api-key": settings.elevenlabs_key}) as r:
        if r.status_code != 200:
            raise RuntimeError(f"ElevenLabs TTS {r.status_code}: {(await r.aread())[:200]!r}")
        async for chunk in r.aiter_bytes():
            buf += chunk
            while len(buf) >= FRAME:
                yield buf[:FRAME]
                buf = buf[FRAME:]
    if buf:
        yield buf + b"\xff" * (FRAME - len(buf))  # 0xFF is mu-law silence


async def transcribe(audio16k: np.ndarray, language: str | None) -> str:
    """One caller utterance (16 kHz float). ElevenLabs Scribe, falling back to faster-whisper."""
    if len(audio16k) < 1600:
        return ""
    if settings.elevenlabs_key and settings.stt == "elevenlabs":
        try:
            t0 = time.time()
            pcm = (np.clip(audio16k, -1, 1) * 32767).astype("<i2").tobytes()
            data = {"model_id": "scribe_v2", "file_format": "pcm_s16le_16", "tag_audio_events": "false"}
            if language:
                data["language_code"] = language
            r = await _client().post(
                f"{ELEVEN}/speech-to-text",
                data=data,
                files={"file": ("utterance.pcm", pcm, "application/octet-stream")},
                headers={"xi-api-key": settings.elevenlabs_key},
            )
            r.raise_for_status()
            log.debug("scribe %.0f ms", (time.time() - t0) * 1000)
            return r.json().get("text", "").strip()
        except Exception as e:
            log.warning("ElevenLabs STT failed, using faster-whisper: %s", e)
    return await asyncio.to_thread(s3_liveness.asr.transcribe, audio16k, "Banking call: balance, block card, change mobile number, payee, limit. ", language)
