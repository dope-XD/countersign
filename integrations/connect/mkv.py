"""Minimal streaming Matroska (MKV/EBML) reader for Kinesis Video Streams audio.

Reads just enough of the format to pull PCM out of a GetMedia response:
track entries (number -> name, codec, sample rate), cluster timecodes,
SimpleBlock/Block payloads and SimpleTags (AWS_KINESISVIDEO_* fragment
metadata, plus the ContactId tag Connect adds). Everything else is skipped.

The reader pulls from any object with ``read(n)`` (a file, a botocore
StreamingBody) and never seeks, so it works on a live, never-ending stream.
GetMedia returns one complete MKV document per fragment back to back, so
a new EBML header simply closes everything that was open and starts again.

Pure stdlib on purpose: this module is meant to move into engine/ingest/.

Spec: https://www.matroska.org/technical/elements.html (element IDs) and
RFC 8794 (EBML variable-size integers).
"""

from __future__ import annotations

import struct
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Protocol

# Element IDs (with their length-marker bits, as they appear on the wire).
EBML = 0x1A45DFA3
SEGMENT = 0x18538067
SEEK_HEAD = 0x114D9B74
INFO = 0x1549A966
TIMECODE_SCALE = 0x2AD7B1
TRACKS = 0x1654AE6B
TRACK_ENTRY = 0xAE
TRACK_NUMBER = 0xD7
TRACK_NAME = 0x536E
CODEC_ID = 0x86
AUDIO = 0xE1
SAMPLING_FREQUENCY = 0xB5
CHANNELS = 0x9F
BIT_DEPTH = 0x6264
CLUSTER = 0x1F43B675
TIMECODE = 0xE7
SIMPLE_BLOCK = 0xA3
BLOCK_GROUP = 0xA0
BLOCK = 0xA1
CUES = 0x1C53BB6B
ATTACHMENTS = 0x1941A469
CHAPTERS = 0x1043A770
TAGS = 0x1254C367
TAG = 0x7373
TARGETS = 0x63C0
SIMPLE_TAG = 0x67C8
TAG_NAME = 0x45A3
TAG_STRING = 0x4487
TAG_BINARY = 0x4485

# Masters we descend into; any other element is read (or skipped) whole.
_MASTERS = {SEGMENT, INFO, TRACKS, TRACK_ENTRY, AUDIO, CLUSTER, BLOCK_GROUP, TAGS, TAG, SIMPLE_TAG}
# Children of Segment: seeing one closes an open unknown-size Cluster.
_SEGMENT_CHILDREN = {SEEK_HEAD, INFO, TRACKS, CLUSTER, CUES, ATTACHMENTS, CHAPTERS, TAGS}
# Leaves we decode; the rest are discarded without being kept in memory.
_KEEP = {
    TIMECODE_SCALE,
    TRACK_NUMBER,
    TRACK_NAME,
    CODEC_ID,
    SAMPLING_FREQUENCY,
    CHANNELS,
    BIT_DEPTH,
    TIMECODE,
    SIMPLE_BLOCK,
    BLOCK,
    TAG_NAME,
    TAG_STRING,
    TAG_BINARY,
}

MAX_LEAF_BYTES = 16 * 1024 * 1024  # a KVS fragment is a few seconds of 8 kHz audio; anything bigger is corrupt
DEFAULT_TIMECODE_SCALE_NS = 1_000_000
_UNKNOWN = -1


class Readable(Protocol):
    def read(self, n: int, /) -> bytes: ...


class MkvError(ValueError):
    """Malformed EBML."""


class TruncatedError(MkvError, EOFError):
    """The stream ended in the middle of an element."""


@dataclass
class Header:
    """An EBML header: a new MKV document (one per KVS fragment) starts here."""

    offset: int


@dataclass
class Track:
    number: int
    name: str = ""
    codec_id: str = ""
    sampling_frequency: float | None = None
    channels: int | None = None
    bit_depth: int | None = None


@dataclass
class ClusterStart:
    timecode: int  # in TimecodeScale units
    timecode_ns: int


@dataclass
class Block:
    track: int
    timecode: int  # absolute: cluster timecode + the block's signed relative offset
    timecode_ns: int
    keyframe: bool
    frames: list[bytes] = field(default_factory=list)

    @property
    def payload(self) -> bytes:
        return b"".join(self.frames)


@dataclass
class SimpleTag:
    name: str
    value: str | bytes | None


Event = Header | Track | ClusterStart | Block | SimpleTag


def _vint_length(first: int) -> int:
    for length in range(1, 9):
        if first & (0x80 >> (length - 1)):
            return length
    raise MkvError("invalid vint: first byte is 0x00")


def read_vint(buf: bytes, pos: int = 0) -> tuple[int, int]:
    """Decode a size-style vint (marker bit removed) from ``buf``. Returns (value, length); all-ones means unknown (-1)."""
    if pos >= len(buf):
        raise TruncatedError("vint past end of buffer")
    length = _vint_length(buf[pos])
    if pos + length > len(buf):
        raise TruncatedError("vint past end of buffer")
    value = buf[pos] & (0xFF >> length)
    for b in buf[pos + 1 : pos + length]:
        value = (value << 8) | b
    if value == (1 << (7 * length)) - 1:
        return _UNKNOWN, length
    return value, length


def _uint(data: bytes) -> int:
    return int.from_bytes(data, "big") if data else 0


def _float(data: bytes) -> float:
    if len(data) == 4:
        return struct.unpack(">f", data)[0]
    if len(data) == 8:
        return struct.unpack(">d", data)[0]
    if not data:
        return 0.0
    raise MkvError(f"float element of {len(data)} bytes")


def _text(data: bytes) -> str:
    return data.rstrip(b"\x00").decode("utf-8", errors="replace")


def parse_block(data: bytes) -> tuple[int, int, int, list[bytes]]:
    """Split a SimpleBlock/Block body into (track, relative timecode, flags, frames), undoing any lacing."""
    track, n = read_vint(data, 0)
    if track == _UNKNOWN or len(data) < n + 3:
        raise MkvError("block header truncated")
    rel = struct.unpack_from(">h", data, n)[0]
    flags = data[n + 2]
    pos = n + 3
    lacing = (flags >> 1) & 0x03
    if lacing == 0:
        return track, rel, flags, [data[pos:]]

    try:
        sizes, pos = _lace_sizes(data, pos, lacing)
    except IndexError as e:
        raise MkvError("lace header truncated") from e
    frames = []
    for size in sizes:
        frames.append(data[pos : pos + size])
        pos += size
    if pos > len(data):
        raise MkvError("laced frame sizes overrun the block")
    frames.append(data[pos:])
    return track, rel, flags, frames


def _lace_sizes(data: bytes, pos: int, lacing: int) -> tuple[list[int], int]:
    """Sizes of all but the last laced frame, and the offset where frame data starts."""
    count = data[pos] + 1
    pos += 1
    sizes: list[int] = []
    if lacing == 1:  # Xiph: each size is a run of 255s plus a final byte
        for _ in range(count - 1):
            size = 0
            while True:
                b = data[pos]
                pos += 1
                size += b
                if b != 255:
                    break
            sizes.append(size)
    elif lacing == 3:  # EBML: first size as a vint, then signed vint deltas
        size, n = read_vint(data, pos)
        pos += n
        sizes.append(size)
        for _ in range(count - 2):
            raw, n = read_vint(data, pos)
            pos += n
            size += raw - ((1 << (7 * n - 1)) - 1)
            sizes.append(size)
    else:  # fixed-size lacing
        total = len(data) - pos
        if total % count:
            raise MkvError("fixed lacing does not divide evenly")
        sizes = [total // count] * (count - 1)
    return sizes, pos


@dataclass
class _Frame:
    id: int
    end: int  # absolute offset, or _UNKNOWN
    ctx: dict


class MkvReader:
    """Pull-based event iterator over an MKV byte stream (use ``iter(reader)`` or ``read_events``)."""

    def __init__(self, stream: Readable, chunk_size: int = 64 * 1024):
        self._stream = stream
        self._chunk_size = chunk_size
        self._buf = bytearray()
        self._pos = 0  # absolute offset of _buf[0]
        self.offset = 0  # absolute offset of the next unread byte
        self.timecode_scale_ns = DEFAULT_TIMECODE_SCALE_NS
        self._cluster_timecode = 0

    # -- byte source --------------------------------------------------------

    def _fill(self, n: int) -> bool:
        """Make sure n unread bytes are buffered. False on clean EOF before any of them arrive."""
        start = self.offset - self._pos
        while len(self._buf) - start < n:
            chunk = self._stream.read(max(self._chunk_size, n - (len(self._buf) - start)))
            if not chunk:
                return False
            self._buf += chunk
        return True

    def _take(self, n: int) -> bytes:
        if not self._fill(n):
            raise TruncatedError(f"stream ended {n} bytes short at offset {self.offset}")
        start = self.offset - self._pos
        out = bytes(self._buf[start : start + n])
        self.offset += n
        if start + n > 1 << 20:  # compact now and then so a long call does not grow the buffer
            del self._buf[: start + n]
            self._pos = self.offset
        return out

    def _skip(self, n: int) -> None:
        while n > 0:
            step = min(n, 1 << 20)
            self._take(step)
            n -= step

    def _read_id(self) -> int | None:
        if not self._fill(1):
            return None
        first = self._buf[self.offset - self._pos]
        length = _vint_length(first)
        if length > 4:
            raise MkvError(f"element ID longer than 4 bytes at offset {self.offset}")
        return _uint(self._take(length))

    def _read_size(self) -> int:
        if not self._fill(1):
            raise TruncatedError("stream ended before element size")
        length = _vint_length(self._buf[self.offset - self._pos])
        value, _ = read_vint(self._take(length))
        return value

    # -- parsing ------------------------------------------------------------

    def __iter__(self) -> Iterator[Event]:
        stack: list[_Frame] = []
        while True:
            # Close known-size masters we have walked past.
            while stack and stack[-1].end != _UNKNOWN and self.offset >= stack[-1].end:
                yield from self._close(stack.pop())
            start = self.offset
            eid = self._read_id()
            if eid is None:
                while stack:
                    yield from self._close(stack.pop())
                return
            size = self._read_size()

            # Unknown-size masters end where an element that cannot be their child begins.
            if eid in (EBML, SEGMENT):
                while stack:
                    yield from self._close(stack.pop())
            elif eid in _SEGMENT_CHILDREN:
                while stack and stack[-1].id != SEGMENT and stack[-1].end == _UNKNOWN:
                    yield from self._close(stack.pop())

            if eid == EBML:
                if size == _UNKNOWN:
                    raise MkvError("EBML header with unknown size")
                self._skip(size)
                yield Header(offset=start)
            elif eid in _MASTERS:
                frame = _Frame(eid, _UNKNOWN if size == _UNKNOWN else self.offset + size, {})
                if eid == TRACK_ENTRY:
                    frame.ctx["track"] = Track(number=0)
                stack.append(frame)
            else:
                if size == _UNKNOWN:
                    raise MkvError(f"leaf element 0x{eid:X} with unknown size at offset {start}")
                if eid not in _KEEP:
                    self._skip(size)
                    continue
                if size > MAX_LEAF_BYTES:
                    raise MkvError(f"element 0x{eid:X} claims {size} bytes")
                yield from self._leaf(eid, self._take(size), stack)

    def _nearest(self, stack: list[_Frame], eid: int) -> dict | None:
        for frame in reversed(stack):
            if frame.id == eid:
                return frame.ctx
        return None

    def _leaf(self, eid: int, data: bytes, stack: list[_Frame]) -> Iterator[Event]:
        if eid == TIMECODE_SCALE:
            self.timecode_scale_ns = _uint(data) or DEFAULT_TIMECODE_SCALE_NS
        elif eid == TIMECODE:
            self._cluster_timecode = _uint(data)
            yield ClusterStart(self._cluster_timecode, self._cluster_timecode * self.timecode_scale_ns)
        elif eid in (SIMPLE_BLOCK, BLOCK):
            track, rel, flags, frames = parse_block(data)
            tc = self._cluster_timecode + rel
            keyframe = bool(flags & 0x80) if eid == SIMPLE_BLOCK else True
            yield Block(track, tc, tc * self.timecode_scale_ns, keyframe, frames)
        elif eid in (TRACK_NUMBER, TRACK_NAME, CODEC_ID, SAMPLING_FREQUENCY, CHANNELS, BIT_DEPTH):
            ctx = self._nearest(stack, TRACK_ENTRY)
            if ctx is None:
                return
            track = ctx["track"]
            if eid == TRACK_NUMBER:
                track.number = _uint(data)
            elif eid == TRACK_NAME:
                track.name = _text(data)
            elif eid == CODEC_ID:
                track.codec_id = _text(data)
            elif eid == SAMPLING_FREQUENCY:
                track.sampling_frequency = _float(data)
            elif eid == CHANNELS:
                track.channels = _uint(data)
            else:
                track.bit_depth = _uint(data)
        elif eid in (TAG_NAME, TAG_STRING, TAG_BINARY):
            ctx = self._nearest(stack, SIMPLE_TAG)
            if ctx is None:
                return
            if eid == TAG_NAME:
                ctx["name"] = _text(data)
            elif eid == TAG_STRING:
                ctx["value"] = _text(data)
            else:
                ctx["value"] = data

    def _close(self, frame: _Frame) -> Iterator[Event]:
        if frame.id == TRACK_ENTRY:
            yield frame.ctx["track"]
        elif frame.id == SIMPLE_TAG and "name" in frame.ctx:
            yield SimpleTag(frame.ctx["name"], frame.ctx.get("value"))


def read_events(stream: Readable) -> Iterator[Event]:
    return iter(MkvReader(stream))
