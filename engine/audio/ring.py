"""Rolling in-memory audio buffer. Nothing here ever touches disk."""
from __future__ import annotations

import numpy as np


class RingBuffer:
    def __init__(self, seconds: float, sample_rate: int):
        self.sr = sample_rate
        self.capacity = int(seconds * sample_rate)
        self._buf = np.zeros(self.capacity, dtype=np.float32)
        self.total = 0  # samples written since the call started

    def write(self, x: np.ndarray) -> None:
        n = len(x)
        if n == 0:
            return
        if n >= self.capacity:
            self._buf[:] = x[-self.capacity :]
        else:
            start = self.total % self.capacity
            end = start + n
            if end <= self.capacity:
                self._buf[start:end] = x
            else:
                k = self.capacity - start
                self._buf[start:] = x[:k]
                self._buf[: n - k] = x[k:]
        self.total += n

    def last(self, n: int) -> np.ndarray:
        """Most recent n samples (fewer if the call is younger than that)."""
        n = min(n, self.capacity, self.total)
        if n == 0:
            return np.zeros(0, dtype=np.float32)
        end = self.total % self.capacity
        start = end - n
        if start >= 0:
            return self._buf[start:end].copy()
        return np.concatenate([self._buf[start:], self._buf[:end]])

    def span(self, t0: int, t1: int) -> np.ndarray:
        """Samples between absolute positions t0 and t1, if still in the buffer."""
        t0 = max(t0, self.total - self.capacity, 0)
        t1 = min(t1, self.total)
        if t1 <= t0:
            return np.zeros(0, dtype=np.float32)
        tail = self.last(self.total - t0)
        return tail[: t1 - t0]

    def wipe(self) -> None:
        self._buf[:] = 0
        self.total = 0
