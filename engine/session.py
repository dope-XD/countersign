"""Call orchestrator: one CallSession per live call.

Caller audio stays at the 8 kHz line rate the whole way: 8 kHz mu-law -> 20 s ring buffer
-> VAD. Every 2 s the last 4 s window is upsampled once to 16 kHz and scored by S1 + S2 in
a worker thread, then fused with S3 + S4 into a tier with reasons for the agent console.
(Upsampling each 20 ms frame separately adds periodic clicks that look synthetic, so
resampling happens per window, never per frame.)
Agent audio is relayed to the caller and used only to time challenge replies.

Calls arrive from the browser softphone (8 kHz mu-law over a websocket) or from Amazon
Connect (engine/ingest/connect.py: 8 kHz PCM out of Kinesis Video Streams). Both end up in
on_caller_pcm / on_agent_pcm. Connect audio arrives a KVS fragment at a time, so its frames
carry the time they were spoken (`wall`) instead of the time they reached us.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from engine import cases, policy
from engine.audio.codec import mulaw_decode, upsample_8k_to_16k
from engine.audio.ring import RingBuffer
from engine.audio.vad import StreamingVAD
from engine.config import settings
from engine.db import db, new_id
from engine.fingerprint import replay_index
from engine.fusion import TIERS, fuse
from engine.hub import hub
from engine.mocks.world import world
from engine.signals import s3_liveness, s4_context
from engine.signals.s1_synth import detector
from engine.signals.s2_drift import CallDrift, embedder

log = logging.getLogger(__name__)
LINE = settings.line_rate  # 8 kHz: every position in this module is in line-rate samples
WINDOW = settings.window_samples // 2  # 4 s window at 8 kHz -> exactly window_samples at 16 kHz
HOP = int(settings.hop_seconds * LINE)
MIN_WINDOWS_FOR_TIER = 2
ASR_LANG = {"en": "en", "hi": "hi", "hinglish": "hi"}


@dataclass
class WindowScore:
    t: float  # seconds into the call (caller track)
    p: float
    drift: float | None
    ms: float


@dataclass
class ActiveChallenge:
    ch: s3_liveness.Challenge
    issued_wall: float
    agent_end_wall: float | None = None
    reply_onset_wall: float | None = None
    reply_onset_pos: int | None = None
    reply_end_pos: int | None = None
    done: bool = False


class Track:
    def __init__(self, keep_audio: bool):
        self.ring = RingBuffer(settings.buffer_seconds, LINE) if keep_audio else None
        self.vad = StreamingVAD(sample_rate=LINE)
        self.pos = 0
        self._arrivals: deque[tuple[int, float]] = deque(maxlen=400)  # (abs pos, wall time) per frame, ~8 s

    def push(self, x: np.ndarray, wall: float | None = None) -> list[tuple[str, int]]:
        """Line-rate float audio. `wall` is when its last sample was spoken (default: now)."""
        if self.ring is not None:
            self.ring.write(x)
        self.pos += len(x)
        self._arrivals.append((self.pos, time.time() if wall is None else wall))
        return self.vad.feed(x)

    def wall_at(self, pos: int) -> float:
        for p, t in self._arrivals:
            if p >= pos:
                return t - (p - pos) / LINE
        return time.time()

    def last_wall(self) -> float | None:
        return self._arrivals[-1][1] if self._arrivals else None


@dataclass
class CallSession:
    id: str
    caller_cli: str
    language: str = "unknown"
    source: str = "softphone"  # softphone | connect | try (a judge's sandbox call, answered by engine/tryout.py)
    customer_id: str | None = None
    started: float = field(default_factory=time.time)
    status: str = "ringing"  # ringing | live | ended
    caller: Track = field(default_factory=lambda: Track(keep_audio=True))
    agent: Track = field(default_factory=lambda: Track(keep_audio=False))
    windows: list[WindowScore] = field(default_factory=list)
    drift: CallDrift = field(default_factory=CallDrift)
    challenge: ActiveChallenge | None = None
    liveness: dict | None = None
    tier: str | None = None
    peak: dict | None = None  # reasons that set the current tier; shown while the live verdict is lower
    verdict: dict | None = None
    request_ids: list[str] = field(default_factory=list)
    case_id: str | None = None
    first_tier_at: float | None = None
    caller_rtt: float = 0.0
    media_delay_s: float | None = None  # Connect: how far behind the live call its audio reaches us
    replay_match: bool = False
    timeline: list[dict] = field(default_factory=list)
    caller_ws: object = None
    agent_wss: set = field(default_factory=set)
    _next_window_pos: int = WINDOW
    _scoring: bool = False

    @property
    def ended(self) -> bool:
        return self.status == "ended"

    def _elapsed(self) -> float:
        return round(time.time() - self.started, 1)

    # ------------------------------------------------------------------ audio in
    async def on_caller_audio(self, mulaw: bytes) -> None:
        await self.on_caller_pcm(mulaw_decode(mulaw))

    async def on_agent_audio(self, mulaw: bytes) -> None:
        await self.on_agent_pcm(mulaw_decode(mulaw))

    async def on_caller_pcm(self, x: np.ndarray, wall: float | None = None) -> None:
        if self.status != "live":
            return
        for kind, pos in self.caller.push(x, wall):
            self._on_caller_vad(kind, pos)
        if self.caller.pos >= self._next_window_pos and not self._scoring:
            self._next_window_pos = self.caller.pos + HOP
            if self.caller.vad.voiced_fraction(self.caller.pos - WINDOW, self.caller.pos) >= settings.min_voiced_fraction:
                self._scoring = True
                asyncio.create_task(self._score(self.caller.ring.last(WINDOW), self.caller.pos / LINE))

    async def on_agent_pcm(self, x: np.ndarray, wall: float | None = None) -> None:
        for kind, pos in self.agent.push(x, wall):
            c = self.challenge
            if kind == "offset" and c and not c.done and c.reply_onset_wall is None:
                wall = self.agent.wall_at(pos)
                if wall > c.issued_wall:
                    c.agent_end_wall = wall

    # ------------------------------------------------------------------ scoring
    async def _score(self, window8k: np.ndarray, t: float) -> None:
        try:
            res, emb, replay = await asyncio.to_thread(self._infer, window8k)
            if self.ended:
                return  # call hung up while scoring: drop the result, audio is already wiped
            drift = self.drift.update(emb)
            self.windows.append(WindowScore(t=t, p=res.p_synthetic, drift=drift, ms=res.ms))
            self.replay_match = self.replay_match or replay
            hub.publish(
                f"call:{self.id}",
                {
                    "type": "window",
                    "t": round(t, 2),
                    "p": round(res.p_synthetic, 4),
                    "drift": None if drift is None else round(drift, 4),
                    "ms": round(res.ms, 1),
                },
            )
            self.recompute()
        except Exception:
            log.exception("scoring failed on call %s", self.id)
        finally:
            self._scoring = False

    def _infer(self, window8k: np.ndarray):
        w16 = upsample_8k_to_16k(window8k)
        res = detector.score([w16])[0]
        emb = embedder.embed([w16])[0]
        replay = False if self.replay_match else replay_index.matches(window8k) is not None
        return res, emb, replay

    def recompute(self) -> None:
        if self.ended:
            return
        if len(self.windows) < MIN_WINDOWS_FOR_TIER and not self.liveness and not self.replay_match:
            hub.publish(f"call:{self.id}", {"type": "state", "call": self.public()})
            return
        now_s = self.caller.pos / LINE
        recent = [w.p for w in self.windows if w.t >= now_s - settings.buffer_seconds] or [w.p for w in self.windows[-3:]]
        ctx = s4_context.evaluate(self.customer_id, self.caller_cli)
        v = fuse(recent, self.drift.max_recent(), self.liveness, ctx.flags, ctx.info, self.replay_match)
        prev = self.tier
        # Within a call the tier only rises: a quieter later stretch never clears an earlier alarm.
        if prev is None or TIERS.index(v.tier) > TIERS.index(prev):
            self.tier = v.tier
            self.peak = {"reasons": v.reasons, "reason_text": v.reason_text}
            if self.first_tier_at is None:
                self.first_tier_at = time.time() - self.started
            self.timeline.append({"t": self._elapsed(), "event": "tier", "tier": v.tier, "reasons": v.reasons})
            db.audit("engine", "tier_changed", self.id, tier=v.tier, reasons=v.reasons, model=detector.version)
        shown = v if v.tier == self.tier else None  # live verdict explains the tier only if it matches it
        self.verdict = {
            "r": round(v.r, 3),
            "voice_tier": v.voice_tier,
            "tier": self.tier,
            "live_tier": v.tier,
            "reasons": shown.reasons if shown else self.peak["reasons"],
            "reason_text": shown.reason_text if shown else self.peak["reason_text"],
            "features": v.features,
            "context": {"flags": ctx.flags, **ctx.info},
            "context_raised": v.context_raised,
            "updated": time.time(),
        }
        if prev != self.tier:
            self._on_tier_change()
        hub.publish(f"call:{self.id}", {"type": "state", "call": self.public()})

    def _on_tier_change(self) -> None:
        for rid in self.request_ids:
            try:
                policy.escalate(rid, self.tier)
            except policy.PolicyError:
                log.warning("could not escalate %s", rid)
        if self.tier == "RED":
            self.ensure_case("tier_red")
            self.attach_evidence()

    def attach_evidence(self) -> None:
        if self.case_id and self.caller.ring.total:
            cases.attach_clip(self.case_id, self.caller.ring.last(int(settings.evidence_seconds * LINE)), LINE)

    def ensure_case(self, event: str) -> str:
        v = self.verdict or {}
        c = cases.open_case(
            channel="contact_centre",
            customer_id=self.customer_id,
            call_id=self.id,
            request_id=self.request_ids[-1] if self.request_ids else None,
            tier=self.tier,
            reasons=v.get("reasons"),
            scores={"r": v.get("r"), **(v.get("features") or {}), "caller_cli": self.caller_cli},
            model_version=detector.version,
            event=event,
        )
        self.case_id = c["id"]
        return c["id"]

    # ------------------------------------------------------------------ liveness (S3)
    def issue_challenge(self, fixed: s3_liveness.Challenge | None = None) -> ActiveChallenge:
        ch = fixed or s3_liveness.new_challenge()
        self.challenge = ActiveChallenge(ch=ch, issued_wall=time.time())
        self.timeline.append({"t": self._elapsed(), "event": "challenge", "kind": ch.kind})
        db.audit("agent", "challenge_issued", self.id, kind=ch.kind)
        return self.challenge

    def agent_done_reading(self) -> None:
        """Manual fallback when the agent's mic isn't connected."""
        if self.challenge and not self.challenge.done:
            self.challenge.agent_end_wall = time.time()

    def _agent_mic_live(self) -> bool:
        last = self.agent.last_wall()
        if self.source == "connect":
            return last is not None  # both legs come from one stream, frame by frame in speaking order
        return last is not None and time.time() - last < 2.0

    def _on_caller_vad(self, kind: str, pos: int) -> None:
        c = self.challenge
        if c is None or c.done:
            return
        if kind == "onset" and c.reply_onset_wall is None:
            if self.source == "try" and c.agent_end_wall is None:
                return  # the judge's phone is still speaking the virtual agent's phrase (its mic is muted meanwhile)
            if self._agent_mic_live() and (self.agent.vad.in_speech or c.agent_end_wall is None):
                return  # the agent is still reading the challenge (or this is its echo)
            wall = self.caller.wall_at(pos)
            if wall > (c.agent_end_wall or c.issued_wall) - 0.3:
                c.reply_onset_wall = wall
                c.reply_onset_pos = pos
        elif kind == "offset" and c.reply_onset_pos is not None and c.reply_end_pos is None:
            c.reply_end_pos = pos
            asyncio.create_task(self._judge_challenge(c))

    async def challenge_timeout(self, c: ActiveChallenge, seconds: float = 10.0) -> None:
        await asyncio.sleep(seconds)
        if c is self.challenge and not c.done and c.reply_end_pos is None:
            if c.reply_onset_pos is not None:
                c.reply_end_pos = self.caller.pos
            await self._judge_challenge(c)

    async def _judge_challenge(self, c: ActiveChallenge) -> None:
        if c.done or c is not self.challenge or self.ended:
            return
        c.done = True
        lag = None
        reply = np.zeros(0, dtype=np.float32)
        if c.reply_onset_wall is not None:
            lag = max(0.0, c.reply_onset_wall - (c.agent_end_wall or c.issued_wall) - self.caller_rtt)
            reply8 = self.caller.ring.span(c.reply_onset_pos - int(0.2 * LINE), c.reply_end_pos or self.caller.pos)
            reply = upsample_8k_to_16k(reply8) if len(reply8) else reply
        if s3_liveness.asr.model is None:
            match = 1.0  # no ASR loaded: judge on timing and S1 only
        else:
            text = await asyncio.to_thread(s3_liveness.asr.transcribe, reply, "", ASR_LANG.get(self.language)) if len(reply) else ""
            match = s3_liveness.content_match(c.ch, text)  # the transcript itself is not kept
        s1_reply = (await asyncio.to_thread(detector.score, [reply]))[0].p_synthetic if len(reply) >= 16000 else None
        if self.ended:
            return
        res = s3_liveness.judge(c.ch, lag, match, s1_reply)
        self.liveness = {
            "passed": res.passed,
            "lag_s": None if lag is None else round(lag, 2),
            "match": round(match, 2),
            "s1_reply": None if s1_reply is None else round(s1_reply, 3),
            "reasons": res.reasons,
            "kind": c.ch.kind,
        }
        db.audit("engine", "liveness_result", self.id, passed=res.passed, reasons=res.reasons, lag=lag)
        self.timeline.append({"t": self._elapsed(), "event": "liveness", **self.liveness})
        for rid in self.request_ids:
            r = policy.get(rid)
            if r["status"] == "open" and r["policy"]["reqs"].get("liveness", {}).get("status") == "pending":
                policy.mark(rid, "liveness", "met" if res.passed else "failed", by="engine", reasons=res.reasons)
        self.recompute()
        hub.publish(f"call:{self.id}", {"type": "liveness", "result": self.liveness})

    # ------------------------------------------------------------------ lifecycle
    def answer(self) -> None:
        if self.status == "ringing":
            self.status = "live"
            self.started = time.time()
            cust = world.by_mobile(self.caller_cli)
            if cust:
                self.customer_id = cust.id  # the IVR matched the caller ID; the agent can change it
                world.calls_by_customer.setdefault(cust.id, []).append(time.time())
            hub.publish("calls", {"type": "calls"})

    def end(self) -> None:
        if self.ended:
            return
        self.status = "ended"
        if self.customer_id:
            world.recent_calls[self.customer_id] = time.time()
        # privacy: drop all audio and embeddings now
        self.caller.ring.wipe()
        self.drift.wipe()
        self.caller.vad.reset()
        self.agent.vad.reset()
        db.audit(
            "engine",
            "call_ended",
            self.id,
            tier=self.tier,
            windows=len(self.windows),
            first_tier_s=self.first_tier_at,
            audio_retained=bool(self.case_id and self.tier == "RED"),
        )
        hub.publish(f"call:{self.id}", {"type": "ended", "call": self.public()})
        hub.publish("calls", {"type": "calls"})

    def audio_seconds_in_memory(self) -> float:
        return 0.0 if self.ended else round(min(self.caller.ring.total, self.caller.ring.capacity) / LINE, 1)

    def public(self) -> dict:
        cust = world.customer(self.customer_id) if self.customer_id else None
        reqs = []
        for rid in self.request_ids:
            r = policy.get(rid)
            reqs.append({**r, "missing": policy.missing(r)})
        ch = self.challenge
        return {
            "id": self.id,
            "caller_cli": self.caller_cli,
            "language": self.language,
            "source": self.source,
            "media_delay_s": None if self.media_delay_s is None else round(self.media_delay_s, 2),
            "status": self.status,
            "customer": cust.__dict__ if cust else None,
            "started": self.started,
            "elapsed": self._elapsed(),
            "tier": self.tier,
            "verdict": self.verdict,
            "windows": [{"t": round(w.t, 2), "p": round(w.p, 3), "drift": w.drift} for w in self.windows[-30:]],
            "challenge": {"id": ch.ch.id, "say": ch.ch.say, "done": ch.done} if ch else None,
            "liveness": self.liveness,
            "requests": reqs,
            "case_id": self.case_id,
            "first_tier_at": self.first_tier_at,
            "model": {"s1": detector.backend, "version": detector.version, "s2": embedder.available},
            "timeline": self.timeline[-30:],
        }


class Calls:
    def __init__(self):
        self.calls: dict[str, CallSession] = {}

    def create(self, caller_cli: str, language: str, source: str = "softphone") -> CallSession:
        cs = CallSession(id=new_id("call"), caller_cli=caller_cli, language=language, source=source)
        self.calls[cs.id] = cs
        db.audit("engine", "call_started", cs.id, cli=caller_cli, source=source)
        hub.publish("calls", {"type": "calls"})
        return cs

    def get(self, cid: str) -> CallSession | None:
        return self.calls.get(cid)

    def live(self) -> list[dict]:
        return [
            {
                "id": c.id,
                "caller_cli": c.caller_cli,
                "status": c.status,
                "tier": c.tier,
                "language": c.language,
                "source": c.source,
                "started": c.started,
                "customer_id": c.customer_id,
            }
            for c in self.calls.values()
            if not c.ended
        ]

    def live_count(self) -> int:
        return sum(1 for c in self.calls.values() if not c.ended)

    def prune(self) -> None:
        now = time.time()
        for cid in [k for k, c in self.calls.items() if c.ended and now - c.started > 3600]:
            del self.calls[cid]


calls = Calls()
