"""Tiny in-process pub/sub that fans JSON events out to websockets.

Topics: "call:<id>" (agent consoles on a call), "desk" (fraud desk), "app:<customer>"
(that customer's phone), "demo" (operator panel), "calls" (list of live calls).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from typing import Any

log = logging.getLogger(__name__)


class Hub:
    def __init__(self):
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self.loop: asyncio.AbstractEventLoop | None = None

    def subscribe(self, *topics: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        for t in topics:
            self._subs[t].add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        for subs in self._subs.values():
            subs.discard(q)

    def has_subscribers(self, topic: str) -> bool:
        return bool(self._subs.get(topic))

    def publish(self, topic: str, event: dict[str, Any]) -> None:
        """Safe to call from any thread."""
        event = {"topic": topic, "ts": time.time(), **event}
        msg = json.dumps(event, default=str)
        if self.loop is None:
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self.loop:
            self._fan(topic, msg)
        else:
            self.loop.call_soon_threadsafe(self._fan, topic, msg)

    def _fan(self, topic: str, msg: str) -> None:
        for q in list(self._subs.get(topic, ())):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                log.warning("dropping event for slow subscriber on %s", topic)


hub = Hub()
