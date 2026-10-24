"""The stronger check: the phone streams its call audio here and gets verdicts back (/ws/listen).

    phone ──16 kHz PCM──► VAD ──utterance──► speech-to-text ──► CallScorer ──► fusion ──► listen_verdict
                                                                      └──► LLM judge (every ~40 words, local)

Audio lives only in memory for the utterance being transcribed, and the transcript only for the
life of the socket. Nothing is written to disk or put in a case. When the verdict reaches "scam",
the server raises the family alarm itself (callcheck.raise_alert, once per call), in case the
phone's own request doesn't get through.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

import numpy as np

from engine.audio.vad import StreamingVAD
from engine.listener.fusion import Judge, Verdict, fuse
from engine.listener.rules import CallScorer

log = logging.getLogger(__name__)

RATE = 16000
MAX_UTTERANCE_S = 8.0  # transcribe long stretches of speech without waiting for a pause
JUDGE_EVERY_WORDS = 40
HEARTBEAT_S = 5.0
ASR_LANG = {"en": "en", "hi": "hi"}  # Hinglish: let the model detect it


class ListenSession:
    def __init__(
        self,
        customer_id: str,
        call_id: str,
        lang: str,
        transcribe: Callable[[np.ndarray, str | None], str],
        judge: Callable[[list[str]], Judge | None] | None,
        send: Callable[[dict], Awaitable[bool]],
        on_scam: Callable[[Verdict], None] | None = None,
    ):
        self.customer_id, self.call_id, self.lang = customer_id, call_id, lang
        self.transcribe, self.judge, self.send, self.on_scam = transcribe, judge, send, on_scam
        self.vad = StreamingVAD(sample_rate=RATE)
        self.scorer = CallScorer()
        self.context: set[str] = set()
        self.heard: list[str] = []
        self.verdict = Verdict("none", "unknown", [], [])
        self.p_scam: float | None = None
        self.abstain = False
        self._judge: Judge | None = None
        self._audio: list[np.ndarray] = []  # samples since the current utterance began
        self._in_speech = False
        self._words_since_judge = 0
        self._judging = False
        self._sent: tuple | None = None
        self._last_sent = 0.0
        self._tasks: set[asyncio.Task] = set()
        self._asr = asyncio.Lock()

    # ------------------------------------------------------------------ input
    async def on_audio(self, pcm: bytes) -> None:
        x = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype="<i2").astype(np.float32) / 32768.0
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
        self._spawn(self._hear(audio))

    def _spawn(self, coro) -> None:
        t = asyncio.create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    # ------------------------------------------------------------------ analysis
    async def _hear(self, audio: np.ndarray) -> None:
        async with self._asr:  # one utterance at a time, in order
            text = await asyncio.to_thread(self.transcribe, audio, ASR_LANG.get(self.lang))
        del audio
        if not text:
            return
        await self.on_text(text)

    async def on_text(self, text: str) -> None:
        self.heard.append(text)
        self.scorer.feed(text)
        self._words_since_judge += len(text.split())
        if self.judge and not self._judging and self._words_since_judge >= JUDGE_EVERY_WORDS and self.verdict.level != "scam":
            self._words_since_judge = 0
            self._judging = True
            self._spawn(self._run_judge(list(self.heard)))
        await self._refresh()

    async def _run_judge(self, heard: list[str]) -> None:
        try:
            j = await asyncio.to_thread(self.judge, heard)
            if j is not None:
                self._judge, self.p_scam, self.abstain = j, j.p_scam, j.abstain
            await self._refresh()
        finally:
            self._judging = False

    async def _refresh(self) -> None:
        before = self.verdict.level
        self.verdict = fuse(self.scorer.result(), self.context, judge=self._judge, prev=before)
        sources = sorted(set(self.verdict.sources) | {"server"})
        self.verdict = Verdict(self.verdict.level, self.verdict.type, self.verdict.cues, sources)
        if self.verdict.level == "scam" and before != "scam" and self.on_scam:
            self.on_scam(self.verdict)
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
                "abstain": self.abstain,
                "at": time.time(),
            }
        )

    async def close(self) -> None:
        for t in list(self._tasks):
            t.cancel()
        self.heard.clear()
        self._audio = []
