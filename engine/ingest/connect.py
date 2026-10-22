"""Amazon Connect calls into the engine.

The contact flow's Lambda (integrations/connect/lambda_start.py) POSTs each new contact's
Kinesis Video Streams position to /api/ingest/connect/start, signed with the shared secret.
The engine opens a call for it, and a worker thread reads the stream with GetMedia:
AUDIO_FROM_CUSTOMER feeds the caller track and AUDIO_TO_CUSTOMER the agent track, both
8 kHz 16-bit PCM, through the same on_caller_pcm / on_agent_pcm path as the softphone. The
agent talks in Connect's own CCP; the Voice Trust Card, requests, liveness and approvals
stay in /agent.

Audio is released one KVS fragment at a time, after the fragment's ContactId tag has been
checked: Connect reuses a stream for the next call, and another caller's audio must never
reach this one. Each frame is stamped with the time it was spoken (the fragment's producer
timestamp plus its offset), so reply lags in the liveness check don't include the KVS delay.

The caller's number is not in the Lambda's payload. A flow that wants caller-ID matching sets
a `cli` contact attribute (e.g. from $.CustomerEndpoint.Address); `lang` (e.g. "hi-IN")
picks the liveness language.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from dataclasses import dataclass, field

import numpy as np
from fastapi import APIRouter, HTTPException, Request

from engine.config import settings
from engine.db import db
from engine.session import LINE, CallSession, calls
from integrations.connect import mkv
from integrations.connect.kvs_dump import DEFAULT_REGION, TAG_CONTACT_ID, TAG_PRODUCER_TS, _is_timeout, parse_kvs_timestamp, region_from_arn
from integrations.connect.lambda_start import DEFAULT_PATH, SIGNATURE_HEADER, verify

log = logging.getLogger(__name__)
router = APIRouter()

CUSTOMER, AGENT = "AUDIO_FROM_CUSTOMER", "AUDIO_TO_CUSTOMER"
FRAME = LINE // 50  # 20 ms, the softphone's frame size
MAX_BODY = 64 * 1024
IDLE_TIMEOUT_S = 10.0
LANGS = {"en": "en", "hi": "hi", "hinglish": "hinglish"}
active: dict[str, CallSession] = {}  # Connect contactId -> call


@dataclass
class Released:
    """One complete fragment of this contact: float audio per track, and when its first sample was spoken."""

    audio: dict[str, np.ndarray]
    spoken_at: float | None


@dataclass
class _Fragment:
    pcm: dict[int, bytearray] = field(default_factory=dict)
    tags: dict[str, str] = field(default_factory=dict)


def pcm16(data: bytes, big_endian: bool = False) -> np.ndarray:
    n = len(data) // 2 * 2
    return np.frombuffer(data[:n], dtype=">i2" if big_endian else "<i2").astype(np.float32) / 32768.0


class ContactMedia:
    """One contact's audio out of a KVS GetMedia event stream, released a fragment at a time."""

    def __init__(self, contact_id: str):
        self.contact_id = contact_id
        self.tracks: dict[int, tuple[str, bool]] = {}  # track number -> (name, big-endian PCM)
        self.current: _Fragment | None = None
        self.done = False  # the stream has moved on to another contact

    def feed(self, event: mkv.Event) -> Released | None:
        """Apply one event. Returns the previous fragment when a new one starts."""
        if isinstance(event, mkv.Header):
            out = self._close()
            self.current = _Fragment()
            return out
        frag = self.current = self.current or _Fragment()
        if isinstance(event, mkv.Track):
            self.tracks.setdefault(event.number, (event.name, event.codec_id.upper().endswith("BIG")))
        elif isinstance(event, mkv.Block):
            frag.pcm.setdefault(event.track, bytearray()).extend(event.payload)
        elif isinstance(event, mkv.SimpleTag):
            value = event.value.decode("utf-8", "replace") if isinstance(event.value, bytes) else event.value
            frag.tags[event.name] = value or ""
        return None

    def finish(self) -> Released | None:
        """The last fragment, once the stream has ended."""
        return self._close()

    def _close(self) -> Released | None:
        frag, self.current = self.current, None
        if frag is None or self.done:
            return None
        owner = frag.tags.get(TAG_CONTACT_ID)
        if owner and owner != self.contact_id:
            self.done = True
            return None
        audio = {}
        for number, data in frag.pcm.items():
            name, big = self.tracks.get(number, ("", False))
            if name in (CUSTOMER, AGENT):
                audio[name] = pcm16(bytes(data), big)
        return Released(audio, parse_kvs_timestamp(frag.tags.get(TAG_PRODUCER_TS)))


async def push(cs: CallSession, rel: Released, arrived: float) -> None:
    """Feed one fragment into the call in 20 ms frames, agent and caller interleaved in speaking order."""
    empty = np.zeros(0, dtype=np.float32)
    caller, agent = rel.audio.get(CUSTOMER, empty), rel.audio.get(AGENT, empty)
    n = max(len(caller), len(agent))
    if rel.spoken_at is not None and n:
        cs.media_delay_s = max(0.0, arrived - (rel.spoken_at + n / LINE))
    for i in range(0, n, FRAME):
        wall = None if rel.spoken_at is None else rel.spoken_at + min(i + FRAME, n) / LINE
        if i < len(agent):
            await cs.on_agent_pcm(agent[i : i + FRAME], wall)
        if i < len(caller):
            await cs.on_caller_pcm(caller[i : i + FRAME], wall)


def open_media(payload: dict):
    """GetMedia for this contact's stream, from the fragment the Lambda reported."""
    from integrations.connect.kvs_dump import open_get_media

    arn = str(payload["streamArn"])
    if payload.get("startFragment"):
        selector = {"StartSelectorType": "FRAGMENT_NUMBER", "AfterFragmentNumber": str(payload["startFragment"])}
    else:
        selector = {"StartSelectorType": "NOW"}
    return open_get_media(arn, selector, region_from_arn(arn) or DEFAULT_REGION, settings.connect_aws_profile or None, IDLE_TIMEOUT_S)


def _stream(cs: CallSession, payload: dict, loop: asyncio.AbstractEventLoop, opener) -> None:
    """Worker thread: read the contact's media until it ends, then end the call."""
    contact = str(payload["contactId"])
    media = ContactMedia(contact)
    reason = "end of stream"

    def send(rel: Released | None) -> None:
        if rel is not None and not cs.ended:
            asyncio.run_coroutine_threadsafe(push(cs, rel, time.time()), loop).result(timeout=30)

    try:
        for event in mkv.MkvReader(opener(payload)):
            if cs.ended:
                reason = "ended in Countersign"
                break
            send(media.feed(event))
            if media.done:
                reason = "stream moved to the next contact"
                break
        else:
            send(media.finish())
    except Exception as e:
        if _is_timeout(e) or isinstance(e, mkv.TruncatedError):
            reason = f"idle: {type(e).__name__}"
            send(media.finish())
        else:
            reason = f"error: {type(e).__name__}"
            log.exception("Connect media for contact %s failed", contact)
    finally:
        log.info("Connect contact %s: %s", contact, reason)
        asyncio.run_coroutine_threadsafe(_finish(cs, contact, reason), loop).result(timeout=10)


async def _finish(cs: CallSession, contact: str, reason: str) -> None:
    db.audit("engine", "connect_stream_ended", cs.id, reason=reason)
    cs.end()
    if active.get(contact) is cs:
        del active[contact]


@router.post(DEFAULT_PATH, status_code=202)
async def connect_start(request: Request) -> dict:
    if not settings.connect_secret:
        raise HTTPException(404, "Amazon Connect ingest is not configured")
    body = await request.body()
    if len(body) > MAX_BODY:
        raise HTTPException(413, "too large")
    if not verify(body, request.headers.get(SIGNATURE_HEADER), settings.connect_secret):
        raise HTTPException(401, "bad or stale signature")
    payload = json.loads(body)
    contact, arn = payload.get("contactId"), payload.get("streamArn")
    if not contact or not arn:
        raise HTTPException(400, "contactId and streamArn are required")
    if contact in active:  # the flow ran the block twice, or the Lambda retried
        return {"call_id": active[contact].id}
    if calls.live_count() >= settings.max_live_calls:
        raise HTTPException(503, "all lines busy")
    attrs = payload.get("attributes") or {}
    cli = str(attrs.get("cli") or "").strip()
    lang = LANGS.get(str(attrs.get("lang") or "").split("-")[0].lower(), "unknown")
    cs = calls.create(cli or "+910000000000", lang, source="connect")
    cs.answer()  # Connect already has the caller; the agent picks it up in the CCP
    active[str(contact)] = cs
    threading.Thread(target=_stream, args=(cs, payload, asyncio.get_running_loop(), open_media), daemon=True, name=f"connect-{cs.id}").start()
    return {"call_id": cs.id}
