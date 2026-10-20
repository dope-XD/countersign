"""Builds synthetic MKV byte streams shaped like a Kinesis Video Streams GetMedia response."""

from __future__ import annotations

import struct

from integrations.connect import mkv

UNKNOWN_SIZE = b"\x01\xff\xff\xff\xff\xff\xff\xff"


def size(n: int) -> bytes:
    for length in range(1, 9):
        if n < (1 << (7 * length)) - 1:
            return ((1 << (7 * length)) | n).to_bytes(length, "big")
    raise ValueError(n)


def eid(i: int) -> bytes:
    return i.to_bytes((i.bit_length() + 7) // 8, "big")


def el(i: int, payload: bytes) -> bytes:
    return eid(i) + size(len(payload)) + payload


def open_el(i: int) -> bytes:
    """Start of an unknown-size master: its children follow."""
    return eid(i) + UNKNOWN_SIZE


def uint(i: int, v: int) -> bytes:
    return el(i, v.to_bytes(max(1, (v.bit_length() + 7) // 8), "big"))


def text(i: int, s: str) -> bytes:
    return el(i, s.encode())


def track_entry(number: int, name: str, codec: str = "A_PCM/INT/LIT", rate: float = 8000.0) -> bytes:
    audio = el(mkv.SAMPLING_FREQUENCY, struct.pack(">d", rate)) + uint(mkv.CHANNELS, 1) + uint(mkv.BIT_DEPTH, 16)
    return el(mkv.TRACK_ENTRY, uint(mkv.TRACK_NUMBER, number) + uint(0x83, 2) + text(mkv.TRACK_NAME, name) + text(mkv.CODEC_ID, codec) + el(mkv.AUDIO, audio))


def simple_block(track: int, rel: int, payload: bytes, flags: int = 0x80) -> bytes:
    return el(mkv.SIMPLE_BLOCK, size(track) + struct.pack(">hB", rel, flags) + payload)


def tags(pairs: dict[str, str]) -> bytes:
    simple = b"".join(el(mkv.SIMPLE_TAG, text(mkv.TAG_NAME, k) + text(mkv.TAG_STRING, v)) for k, v in pairs.items())
    return el(mkv.TAGS, el(mkv.TAG, el(mkv.TARGETS, b"") + simple))


EBML_HEADER = el(mkv.EBML, uint(0x4286, 1) + text(0x4282, "matroska"))


def fragment(
    cluster_ms: int,
    blocks: list[tuple[int, int, bytes]],
    frag_tags: dict[str, str],
    codec: str = "A_PCM/INT/LIT",
    known_size_cluster: bool = False,
) -> bytes:
    """One KVS chunk: EBML header, unknown-size Segment, Info, Tracks, Cluster of blocks, then Tags."""
    tracks = el(mkv.TRACKS, track_entry(1, "AUDIO_FROM_CUSTOMER", codec) + track_entry(2, "AUDIO_TO_CUSTOMER", codec))
    info = el(mkv.INFO, uint(mkv.TIMECODE_SCALE, 1_000_000) + el(0xEC, b"\x00" * 5))  # plus a Void to skip
    body = uint(mkv.TIMECODE, cluster_ms) + b"".join(simple_block(t, rel, p) for t, rel, p in blocks)
    cluster = el(mkv.CLUSTER, body) if known_size_cluster else open_el(mkv.CLUSTER) + body
    return EBML_HEADER + open_el(mkv.SEGMENT) + info + tracks + cluster + tags(frag_tags)


def pcm(n_samples: int, start: int = 0) -> bytes:
    return b"".join(struct.pack("<h", (start + i) % 30000) for i in range(n_samples))
