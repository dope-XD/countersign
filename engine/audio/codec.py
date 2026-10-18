"""G.711 mu-law and resampling helpers.

The softphone sends 8 kHz mu-law, exactly what a PSTN leg carries, so every score the
engine produces is on phone-quality audio.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import resample_poly

_BIAS = 0x84
_CLIP = 32635


def _build_decode_table() -> np.ndarray:
    table = np.zeros(256, dtype=np.int16)
    for i in range(256):
        u = ~i & 0xFF
        sign = u & 0x80
        exponent = (u >> 4) & 0x07
        mantissa = u & 0x0F
        sample = ((mantissa << 3) + _BIAS) << exponent
        sample -= _BIAS
        table[i] = -sample if sign else sample
    return table


_DECODE = _build_decode_table()
_EXP_LUT = np.array([0, 0, 1, 1, 2, 2, 2, 2] + [3] * 8 + [4] * 16 + [5] * 32 + [6] * 64 + [7] * 128, dtype=np.int32)


def mulaw_decode(data: bytes) -> np.ndarray:
    """mu-law bytes -> float32 in [-1, 1]."""
    idx = np.frombuffer(data, dtype=np.uint8)
    return _DECODE[idx].astype(np.float32) / 32768.0


def mulaw_encode(x: np.ndarray) -> bytes:
    """float32 in [-1, 1] -> mu-law bytes (ITU-T G.711)."""
    pcm = np.clip(np.round(x * 32768.0), -32768, 32767).astype(np.int32)
    sign = np.where(pcm < 0, 0x80, 0)
    mag = np.minimum(np.abs(pcm), _CLIP) + _BIAS
    exponent = _EXP_LUT[(mag >> 7) & 0xFF]
    mantissa = (mag >> (exponent + 3)) & 0x0F
    out = ~(sign | (exponent << 4) | mantissa) & 0xFF
    return out.astype(np.uint8).tobytes()


def upsample_8k_to_16k(x: np.ndarray) -> np.ndarray:
    return resample_poly(x, 2, 1).astype(np.float32)


def resample(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    if sr_in == sr_out:
        return x.astype(np.float32)
    from math import gcd

    g = gcd(sr_in, sr_out)
    return resample_poly(x, sr_out // g, sr_in // g).astype(np.float32)


def phone_line(x16k: np.ndarray) -> np.ndarray:
    """Simulate a G.711 leg on 16 kHz audio: down to 8 kHz, mu-law round trip, back up."""
    x8 = resample(x16k, 16000, 8000)
    x8 = mulaw_decode(mulaw_encode(x8))
    return upsample_8k_to_16k(x8)
