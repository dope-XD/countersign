import numpy as np

from engine.audio.codec import mulaw_decode, mulaw_encode
from engine.fingerprint import ReplayIndex, landmarks
from engine.mocks.world import world  # noqa: F401  (imports the DB the index persists to)

SR = 8000


def _melody(seed: int, seconds: float = 6.0) -> np.ndarray:
    """Distinctive test audio: 80 ms tone bursts at random frequencies with harmonics."""
    rng = np.random.default_rng(seed)
    n = int(SR * 0.08)
    t = np.arange(n) / SR
    parts = []
    for _ in range(int(seconds / 0.08)):
        f = rng.uniform(350, 1500)
        parts.append((np.sin(2 * np.pi * f * t) + 0.5 * np.sin(4 * np.pi * f * t)) * np.hanning(n))
    x = np.concatenate(parts).astype(np.float32)
    return 0.4 * x / np.abs(x).max()


def _over_phone_line(x: np.ndarray, shift_s: float, gain: float) -> np.ndarray:
    y = x[int(shift_s * SR) :] * gain
    y = y + np.random.default_rng(9).normal(0, 0.003, len(y)).astype(np.float32)
    return mulaw_decode(mulaw_encode(y))


def test_landmarks_are_deterministic():
    x = _melody(1)
    assert landmarks(x) == landmarks(x.copy()) and len(landmarks(x)) > 100


def test_replay_matches_through_codec_shift_and_gain_but_not_other_audio():
    idx = ReplayIndex()
    idx.clear()
    idx.add("case_a", _melody(1))
    probe = _over_phone_line(_melody(1), shift_s=0.3, gain=0.5)[: 4 * SR]
    assert idx.matches(probe) == "case_a"
    for seed in (2, 3, 4):
        assert idx.matches(_over_phone_line(_melody(seed), 0.0, 1.0)[: 4 * SR]) is None
    idx.clear()
    assert idx.matches(probe) is None
