"""Call orchestrator: one CallSession per live call.

Caller audio (8 kHz mu-law) -> 20 s ring buffer at 16 kHz -> VAD -> a 4 s window every
2 s -> S1 + S2 in a worker thread -> fusion with S3 + S4 -> tier + reasons -> agent console.
Agent audio is relayed to the caller and used only to time challenge replies.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

import numpy as np

from engine import cases, policy
from engine.audio.codec import mulaw_decode, upsample_8k_to_16k
from engine.audio.ring import RingBuffer
from engine.audio.vad import StreamingVAD
from engine.config import settings
from engine.db import db, new_id
from engine.fusion import TIERS, fuse
from engine.hub import hub
from engine.mocks.world import world
from engine.signals import s3_liveness, s4_context
from engine.signals.s1_synth import detector
from engine.signals.s2_drift import CallDrift, embedder

log = logging.getLogger(__name__)
SR = settings.sample_rate
MIN_WINDOWS_FOR_TIER = 2


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
        self.ring = RingBuffer(settings.buffer_seconds, SR) if keep_audio else None
        self.vad = StreamingVAD()
        self.pos = 0
        self._arrivals: list[tuple[int, float]] = []  # (abs pos, wall time) per frame

    def push(self, mulaw: bytes) -> tuple[np.ndarray, list[tuple[str, int]]]:
        x = upsample_8k_to_16k(mulaw_decode(mulaw))
        if self.ring is not None:
            self.ring.write(x)
        self.pos += len(x)
        self._arrivals.append((self.pos, time.time()))
        self._arrivals = self._arrivals[-400:]
        return x, self.vad.feed(x)

    def wall_at(self, pos: int) -> float:
        for p, t in self._arrivals:
            if p >= pos:
                return t - (p - pos) / SR
        return time.time()


@dataclass
class CallSession:
    id: str
    caller_cli: str
    language: str = "unknown"
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
    verdict: dict | None = None
    request_ids: list[str] = field(default_factory=list)
    case_id: str | None = None
    first_tier_at: float | None = None
    _next_window_pos: int = int(settings.window_samples)
    _scoring: bool = False
    caller_rtt: float = 0.0
    replay_match: bool = False
    timeline: list[dict] = field(default_factory=list)
    caller_ws: object = None
    agent_wss: set = field(default_factory=set)

    # ------------------------------------------------------------------ audio in
    async def on_caller_audio(self, mulaw: bytes) -> None:
        if self.status == "ringing":
            return
        x, events = self.caller.push(mulaw)
        for kind, pos in events:
            self._on_caller_vad(kind, pos)
        if self.caller.pos >= self._next_window_pos and not self._scoring:
            self._next_window_pos = self.caller.pos + int(settings.hop_seconds * SR)
            t0 = self.caller.pos - settings.window_samples
            if self.caller.vad.voiced_fraction(t0, self.caller.pos) >= settings.min_voiced_fraction:
                self._scoring = True
                window = self.caller.ring.last(settings.window_samples)
                asyncio.create_task(self._score(window, self.caller.pos / SR))

    async def on_agent_audio(self, mulaw: bytes) -> None:
        _x, events = self.agent.push(mulaw)
        for kind, pos in events:
            if kind == "offset" and self.challenge and not self.challenge.done and self.challenge.reply_onset_wall is None:
                wall = self.agent.wall_at(pos)
                if wall > self.challenge.issued_wall:
                    self.challenge.agent_end_wall = wall

    # ------------------------------------------------------------------ scoring
    async def _score(self, window: np.ndarray, t: float) -> None:
        try:
            res, emb = await asyncio.to_thread(self._infer, window)
            drift = self.drift.update(emb)
            self.windows.append(WindowScore(t=t, p=res.p_synthetic, drift=drift, ms=res.ms))
            hub.publish(f"call:{self.id}", {"type": "window", "t": round(t, 2), "p": round(res.p_synthetic, 4),
                                            "drift": None if drift is None else round(drift, 4), "ms": round(res.ms, 1)})
            self._replay_check(window)
            self.recompute()
        except Exception:
            log.exception("scoring failed on call %s", self.id)
        finally:
            self._scoring = False

    @staticmethod
    def _infer(window: np.ndarray):
        res = detector.score([window])[0]
        emb = embedder.embed([window])[0]
        return res, emb

    def _replay_check(self, window: np.ndarray) -> None:
        if self.replay_match:
            return
        h = cases.audio_hash(window)
        if h and db.query("SELECT 1 FROM replay_hashes WHERE hash=?", [h]):
            self.replay_match = True

    def recompute(self) -> None:
        if len(self.windows) < MIN_WINDOWS_FOR_TIER and not self.liveness:
            hub.publish(f"call:{self.id}", {"type": "state", "call": self.public()})
            return
        recent = [w.p for w in self.windows if w.t >= self.caller.pos / SR - settings.buffer_seconds]
        ctx = s4_context.evaluate(self.customer_id, self.caller_cli)
        v = fuse(recent or [w.p for w in self.windows[-3:]], self.drift.max_recent(), self.liveness, ctx.flags, ctx.info, self.replay_match)
        prev = self.tier
        # Tier within a call only rises; a quieter later stretch never clears an earlier alarm.
        if prev is None or TIERS.index(v.tier) > TIERS.index(prev):
            self.tier = v.tier
            if self.first_tier_at is None:
                self.first_tier_at = time.time() - self.started
            self.timeline.append({"t": round(time.time() - self.started, 1), "event": "tier", "tier": v.tier, "reasons": v.reasons})
            db.audit("engine", "tier_changed", self.id, tier=v.tier, reasons=v.reasons, model=detector.version)
        self.verdict = {
            "r": round(v.r, 3), "voice_tier": v.voice_tier, "tier": self.tier, "live_tier": v.tier,
            "reasons": v.reasons, "reason_text": v.reason_text, "features": v.features,
            "context": {"flags": ctx.flags, **ctx.info}, "context_raised": v.context_raised,
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
                pass
        if self.tier == "RED":
            self.ensure_case("tier_red")
            cases.attach_clip(self.case_id, self.caller.ring.last(int(settings.evidence_seconds * SR)))

    def ensure_case(self, event: str) -> str:
        v = self.verdict or {}
        c = cases.open_case(
            channel="contact_centre", customer_id=self.customer_id, call_id=self.id,
            request_id=self.request_ids[-1] if self.request_ids else None, tier=self.tier,
            reasons=v.get("reasons"), scores={"r": v.get("r"), **(v.get("features") or {}), "caller_cli": self.caller_cli},
            model_version=detector.version, event=event,
        )
        self.case_id = c["id"]
        return c["id"]

    # ------------------------------------------------------------------ liveness (S3)
    def issue_challenge(self, fixed: s3_liveness.Challenge | None = None) -> dict:
        ch = fixed or s3_liveness.new_challenge()
        self.challenge = ActiveChallenge(ch=ch, issued_wall=time.time())
        self.timeline.append({"t": round(time.time() - self.started, 1), "event": "challenge", "kind": ch.kind})
        db.audit("agent", "challenge_issued", self.id, kind=ch.kind)
        return {"id": ch.id, "say": ch.say, "kind": ch.kind}

    def agent_done_reading(self) -> None:
        """Manual fallback when the agent's mic isn't connected."""
        if self.challenge and not self.challenge.done:
            self.challenge.agent_end_wall = time.time()

    def _on_caller_vad(self, kind: str, pos: int) -> None:
        c = self.challenge
        if c is None or c.done:
            return
        if kind == "onset" and c.reply_onset_wall is None:
            wall = self.caller.wall_at(pos)
            agent_mic_live = self.agent.pos > 0 and time.time() - self.agent.wall_at(self.agent.pos) < 2.0
            if agent_mic_live and (self.agent.vad.in_speech or c.agent_end_wall is None):
                return  # agent is still reading the challenge (or echo of it)
            ref = c.agent_end_wall or c.issued_wall
            if wall > ref - 0.3:
                c.reply_onset_wall = wall
                c.reply_onset_pos = pos
        elif kind == "offset" and c.reply_onset_pos is not None and c.reply_end_pos is None:
            c.reply_end_pos = pos
            asyncio.create_task(self._judge_challenge())

    async def check_challenge_timeout(self, seconds: float = 8.0) -> None:
        await asyncio.sleep(seconds)
        c = self.challenge
        if c and not c.done and c.reply_end_pos is None:
            if c.reply_onset_pos is not None:
                c.reply_end_pos = self.caller.pos
            await self._judge_challenge()

    async def _judge_challenge(self) -> None:
        c = self.challenge
        if c is None or c.done:
            return
        c.done = True
        lag = None
        reply = np.zeros(0, dtype=np.float32)
        if c.reply_onset_wall is not None:
            ref = c.agent_end_wall or c.issued_wall
            lag = max(0.0, c.reply_onset_wall - ref - self.caller_rtt)
            reply = self.caller.ring.span(c.reply_onset_pos - int(0.2 * SR), c.reply_end_pos or self.caller.pos)
        lang = {"en": "en", "hi": "hi", "hinglish": "hi"}.get(self.language)
        text = await asyncio.to_thread(s3_liveness.asr.transcribe, reply, "", lang) if len(reply) else ""
        match = s3_liveness.content_match(c.ch, text) if s3_liveness.asr.model is not None else 1.0
        s1_reply = None
        if len(reply) >= SR:
            s1_reply = (await asyncio.to_thread(detector.score, [reply]))[0].p_synthetic
        res = s3_liveness.judge(c.ch, lag, match, s1_reply)
        # transcript is discarded here; only pass/fail and timings are kept
        self.liveness = {"passed": res.passed, "lag_s": None if lag is None else round(lag, 2), "match": round(match, 2),
                         "s1_reply": None if s1_reply is None else round(s1_reply, 3), "reasons": res.reasons, "kind": c.ch.kind}
        db.audit("engine", "liveness_result", self.id, passed=res.passed, reasons=res.reasons, lag=lag)
        self.timeline.append({"t": round(time.time() - self.started, 1), "event": "liveness", **self.liveness})
        for rid in self.request_ids:
            r = policy.get(rid)
            if "liveness" in r["policy"]["reqs"] and r["policy"]["reqs"]["liveness"]["status"] == "pending":
                policy.mark(rid, "liveness", "met" if res.passed else "failed", by="engine", reasons=res.reasons)
        self.recompute()
        hub.publish(f"call:{self.id}", {"type": "liveness", "result": self.liveness})

    # ------------------------------------------------------------------ lifecycle
    def answer(self) -> None:
        self.status = "live"
        self.started = time.time()
        hub.publish("calls", {"type": "calls"})

    def end(self) -> None:
        if self.status == "ended":
            return
        self.status = "ended"
        if self.customer_id:
            world.recent_calls[self.customer_id] = time.time()
        # privacy: drop all audio and embeddings now
        self.caller.ring.wipe()
        self.drift.wipe()
        self.caller.vad.reset()
        self.agent.vad.reset()
        db.audit("engine", "call_ended", self.id, tier=self.tier, windows=len(self.windows),
                 first_tier_s=self.first_tier_at, audio_retained=bool(self.case_id and self.tier == "RED"))
        hub.publish(f"call:{self.id}", {"type": "ended", "call": self.public()})
        hub.publish("calls", {"type": "calls"})

    def public(self) -> dict:
        cust = world.customer(self.customer_id) if self.customer_id else None
        return {
            "id": self.id, "caller_cli": self.caller_cli, "language": self.language, "status": self.status,
            "customer": cust.__dict__ if cust else None, "started": self.started,
            "elapsed": round(time.time() - self.started, 1), "tier": self.tier, "verdict": self.verdict,
            "windows": [{"t": round(w.t, 2), "p": round(w.p, 3), "drift": w.drift} for w in self.windows[-30:]],
            "challenge": {"id": self.challenge.ch.id, "say": self.challenge.ch.say, "done": self.challenge.done} if self.challenge else None,
            "liveness": self.liveness, "requests": [policy.get(r) for r in self.request_ids],
            "case_id": self.case_id, "first_tier_at": self.first_tier_at, "model": {"s1": detector.backend, "version": detector.version, "s2": embedder.available},
            "timeline": self.timeline[-30:],
        }


class Calls:
    def __init__(self):
        self.calls: dict[str, CallSession] = {}

    def create(self, caller_cli: str, language: str) -> CallSession:
        cs = CallSession(id=new_id("call"), caller_cli=caller_cli, language=language)
        self.calls[cs.id] = cs
        cust = world.by_mobile(caller_cli)
        db.audit("engine", "call_started", cs.id, cli=caller_cli)
        hub.publish("calls", {"type": "calls", "suggested_customer": cust.id if cust else None})
        return cs

    def get(self, cid: str) -> CallSession | None:
        return self.calls.get(cid)

    def live(self) -> list[dict]:
        return [
            {"id": c.id, "caller_cli": c.caller_cli, "status": c.status, "tier": c.tier, "language": c.language,
             "started": c.started, "customer_id": c.customer_id}
            for c in self.calls.values() if c.status != "ended"
        ]

    def prune(self) -> None:
        now = time.time()
        for cid in [k for k, c in self.calls.items() if c.status == "ended" and now - c.started > 3600]:
            del self.calls[cid]


calls = Calls()
