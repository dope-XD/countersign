"""The server's stronger check (`/ws/listen`): the phone streams a suspicious call here and gets verdicts back.

    phone ──16 kHz PCM──► VAD ──utterance──► speech-to-text (Omnilingual 1B) ──► the conversation check ──┐
                     └──► 4 s windows of speech ──► S1, the full AntiDeepfake W2V-Large (24 layers) ───────┴► listen_verdict

The conversation check is the phone's own (engine/listener/conversation.py: the fine-tuned conversation model, the
move matcher, the accumulator), run here on better audio and a larger speech-to-text model. Without those models on
the laptop it falls back to basic mode (cue rules + the small classifier through fusion).

When it runs: the phone always checks the call itself first; only once the phone's own level reaches amber does
it open this socket (a likely scam is what the stronger check is for). The server can raise the level, never
lower it, and its verdict is one more source in the phone's fusion.

What is kept (docs/RESULTS.md, Round 1 plan "What Countersign keeps"): audio lives in memory, in a rolling 20 s
buffer, and is dropped when the socket closes. Only if this call reaches "scam" does the server keep that last 20 s
as an AES-256 encrypted evidence clip in a fraud case, deleted after 30 days or when the case closes. Transcripts
are never stored; the case holds the tier, the scam type and cue ids.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

import numpy as np

from engine.audio.vad import StreamingVAD
from engine.listener.classifier import classifier
from engine.listener.fusion import LEVELS, Verdict, fuse
from engine.listener.rules import CallScorer

log = logging.getLogger(__name__)


def conversation_call():
    """A conversation-check call, or None (basic mode) when the models aren't on this laptop."""
    from engine.listener import conversation

    try:
        conversation.conv_model(), conversation.base_model(), conversation.config()
    except Exception as e:  # noqa: BLE001 - any missing file or runtime means basic mode
        log.warning("conversation models not loaded, basic mode: %s", e)
        return None
    return conversation.Call()

RATE = 16000
MAX_UTTERANCE_S = 8.0
HEARTBEAT_S = 5.0
EVIDENCE_S = 20.0
S1_WINDOW = 64600  # ~4 s, what the voice model was built for
S1_RED = 0.70  # Round 1's RED cut-off on the calibrated S1 score


class ListenSession:
    def __init__(
        self,
        customer_id: str,
        call_id: str,
        lang: str,
        transcribe: Callable[[np.ndarray, str | None], str],
        voice: Callable[[list[np.ndarray]], list[float]] | None,
        send: Callable[[dict], Awaitable[bool]],
        on_scam: Callable[[Verdict, np.ndarray], None] | None = None,
    ):
        self.customer_id, self.call_id, self.lang = customer_id, call_id, lang
        self.transcribe, self.voice, self.send, self.on_scam = transcribe, voice, send, on_scam
        self.vad = StreamingVAD(sample_rate=RATE)
        self.conv = conversation_call()
        self.scorer = CallScorer()
        self.clf = classifier()
        self.context: set[str] = set()
        self.heard: list[str] = []
        self.verdict = Verdict("none", "unknown", [], [])
        self.p_scam: float | None = None
        self.s1: list[float] = []
        self._audio: list[np.ndarray] = []
        self._speech: list[np.ndarray] = []  # speech not yet scored by S1
        self._ring = np.zeros(0, dtype=np.float32)  # the last EVIDENCE_S seconds, for a RED case only
        self._in_speech = False
        self._sent: tuple | None = None
        self._last_sent = 0.0
        self._tasks: set[asyncio.Task] = set()
        self._asr = asyncio.Lock()
        self._conv_lock = asyncio.Lock()

    # ------------------------------------------------------------------ input
    async def on_audio(self, pcm: bytes) -> None:
        x = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype="<i2").astype(np.float32) / 32768.0
        self._ring = np.concatenate([self._ring, x])[-int(EVIDENCE_S * RATE) :]
        for kind, _pos in self.vad.feed(x):
            if kind == "onset":
                self._in_speech, self._audio = True, []
            elif kind == "offset" and self._in_speech:
                self._in_speech = False
                self._flush()
        if self._in_speech:
            self._audio.append(x)
            if sum(len(a) for a in self._audio) >= MAX_UTTERANCE_S * RATE:
                self._flush()
        if time.time() - self._last_sent >= HEARTBEAT_S:
            await self._publish(force=True)

    async def on_context(self, signals: list[str], caller_check: str | None) -> None:
        ctx = {s for s in signals if isinstance(s, str) and len(s) <= 40}
        if caller_check in ("not_them", "not_with_you", "no"):
            ctx.add("caller_check_failed")
        elif caller_check in ("verified", "likely", "yes"):
            ctx.add("caller_verified")
        self.context = ctx
        await self._refresh()

    def _flush(self) -> None:
        if not self._audio:
            return
        audio, self._audio = np.concatenate(self._audio), []
        self._speech.append(audio)
        self._spawn(self._hear(audio))
        if self.voice and sum(len(a) for a in self._speech) >= S1_WINDOW:
            speech, self._speech = np.concatenate(self._speech), []
            windows = [speech[i : i + S1_WINDOW] for i in range(0, len(speech) - S1_WINDOW + 1, S1_WINDOW)]
            self._spawn(self._score_voice(windows))

    def _spawn(self, coro) -> None:
        t = asyncio.create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    # ------------------------------------------------------------------ analysis
    async def _hear(self, audio: np.ndarray) -> None:
        async with self._asr:  # one utterance at a time, in order
            text = await asyncio.to_thread(self.transcribe, audio, self.lang)
        del audio
        if text:
            await self.on_text(text)

    async def _score_voice(self, windows: list[np.ndarray]) -> None:
        probs = await asyncio.to_thread(self.voice, windows)
        self.s1 = (self.s1 + list(probs))[-5:]
        # Round 1's call score: the mean of the top 3 windows in the last 20 s
        top = sorted(self.s1, reverse=True)[:3]
        if top and float(np.mean(top)) >= S1_RED:
            self.context.add("synthetic_voice")
        await self._refresh()

    async def on_text(self, text: str) -> None:
        self.heard.append(text)
        if self.conv is not None:
            async with self._conv_lock:  # segments in order, one at a time
                await asyncio.to_thread(self.conv.feed, text)
        else:
            self.scorer.feed(text)
        await self._refresh()

    async def _refresh(self) -> None:
        before = self.verdict.level
        if self.conv is not None:
            st = self.conv.set_context(self.context)
            self.p_scam = st.p
            level = st.level if LEVELS.index(st.level) >= LEVELS.index(before) else before
            self.verdict = Verdict(level, st.type, st.reasons, sorted(set(st.sources) | {"server"}))
        else:
            j = self.clf.judge(" ".join(self.heard))
            self.p_scam = None if j.abstain else j.p_scam
            v = fuse(self.scorer.result(), self.context, judge=j, prev=before)
            self.verdict = Verdict(v.level, v.type, v.cues, sorted(set(v.sources) | {"server"}))
        if self.verdict.level == "scam" and before != "scam" and self.on_scam:
            self.on_scam(self.verdict, self._ring.copy())
        await self._publish()

    async def _publish(self, force: bool = False) -> None:
        key = (self.verdict.level, self.verdict.type, tuple(self.verdict.cues))
        if key == self._sent and not force:
            return
        self._sent, self._last_sent = key, time.time()
        await self.send(
            {
                "type": "listen_verdict",
                "level": self.verdict.level,
                "scam_type": self.verdict.type,
                "p_scam": self.p_scam,
                "cues": self.verdict.cues,
                "voice": round(float(np.mean(sorted(self.s1, reverse=True)[:3])), 3) if self.s1 else None,
                "abstain": False,
                "at": time.time(),
            }
        )

    async def close(self) -> None:
        for t in list(self._tasks):
            t.cancel()
        self.heard.clear()
        self._audio, self._speech = [], []
        self._ring = np.zeros(0, dtype=np.float32)
