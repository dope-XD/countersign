"""Training/dev datasets for S1. Kept free of transformers so DataLoader workers stay small
(each Windows worker re-imports this module)."""
from __future__ import annotations

import csv
import random
import time

import numpy as np
import torch
from torch.utils.data import Dataset, Sampler

from ml.augment.telephony import channel, load_audio, random_phone_chain

N_SAMPLES = 64600


def read(path: str) -> list[dict]:
    return list(csv.DictReader(open(path, encoding="utf-8")))


def crop(x: np.ndarray, rng: random.Random, n: int = N_SAMPLES) -> np.ndarray:
    if len(x) >= n:
        s = rng.randrange(0, len(x) - n + 1)
        return x[s : s + n]
    reps = n // max(1, len(x)) + 1
    return np.tile(x, reps)[:n]


class TrainSet(Dataset):
    def __init__(self, rows: list[dict], seed: int = 0):
        self.rows = rows
        self.seed = seed

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        rng = random.Random(hash((self.seed, i, time.time_ns())))
        r = self.rows[i]
        x = crop(load_audio(r["path"]), rng)
        try:
            x, _ = random_phone_chain(x, rng)
        except Exception:
            pass  # a codec hiccup shouldn't kill the epoch; the clean clip is still useful
        x = crop(x, rng)
        y = 1 if r["label"] == "bonafide" else 0
        return torch.from_numpy(np.ascontiguousarray(x, dtype=np.float32)), y


class DevSet(Dataset):
    """Deterministic: first 4 s, each clip through one fixed channel (cycled)."""

    CHANNELS = ["g711u", "amrnb_12k2", "opus_12k", "clean", "gsm"]

    def __init__(self, rows: list[dict]):
        self.rows = rows

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        r = self.rows[i]
        x = load_audio(r["path"])[:N_SAMPLES]
        x = channel(x, self.CHANNELS[i % len(self.CHANNELS)])
        x = np.tile(x, N_SAMPLES // max(1, len(x)) + 1)[:N_SAMPLES]
        return torch.from_numpy(np.ascontiguousarray(x, dtype=np.float32)), 1 if r["label"] == "bonafide" else 0


class BalancedSampler(Sampler):
    """Half bona fide, half spoof; within each half, sources are drawn evenly."""

    def __init__(self, rows: list[dict], n: int, seed: int = 0):
        self.n = n
        self.rng = random.Random(seed)
        self.groups: dict[tuple[str, str], list[int]] = {}
        for i, r in enumerate(rows):
            self.groups.setdefault((r["label"], r["source"]), []).append(i)

    def __len__(self):
        return self.n

    def __iter__(self):
        bona = [g for g in self.groups if g[0] == "bonafide"]
        spoof = [g for g in self.groups if g[0] != "bonafide"]
        for k in range(self.n):
            keys = bona if k % 2 == 0 else spoof
            g = self.rng.choice(keys)
            yield self.rng.choice(self.groups[g])
