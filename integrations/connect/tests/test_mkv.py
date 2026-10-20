import io
import struct

import pytest

from integrations.connect import mkv
from integrations.connect.tests import mkvbuild as b


class Trickle(io.RawIOBase):
    """Hands out at most one byte per read, like a slow chunked HTTP body."""

    def __init__(self, data: bytes):
        self.data, self.pos = data, 0

    def read(self, n=-1):
        out = self.data[self.pos : self.pos + 1]
        self.pos += len(out)
        return out


def two_fragments(**kw) -> bytes:
    f1 = b.fragment(
        1000,
        [(1, 0, b.pcm(160)), (2, 0, b.pcm(160, 7)), (1, 20, b.pcm(160, 160))],
        {"AWS_KINESISVIDEO_FRAGMENT_NUMBER": "91343852333181432392682062606740271849390003051", "ContactId": "c-1"},
        **kw,
    )
    f2 = b.fragment(1040, [(1, 0, b.pcm(160, 320))], {"AWS_KINESISVIDEO_FRAGMENT_NUMBER": "91343852333181432392682062606740271849390003052"}, **kw)
    return f1 + f2


@pytest.mark.parametrize("known_size_cluster", [False, True])
@pytest.mark.parametrize("trickle", [False, True])
def test_reads_tracks_blocks_and_tags(known_size_cluster, trickle):
    data = two_fragments(known_size_cluster=known_size_cluster)
    stream = Trickle(data) if trickle else io.BytesIO(data)
    events = list(mkv.read_events(stream))

    kinds = [type(e).__name__ for e in events]
    assert kinds.count("Header") == 2
    assert kinds[0] == "Header"

    tracks = [e for e in events if isinstance(e, mkv.Track)]
    assert [(t.number, t.name) for t in tracks[:2]] == [(1, "AUDIO_FROM_CUSTOMER"), (2, "AUDIO_TO_CUSTOMER")]
    assert tracks[0].codec_id == "A_PCM/INT/LIT"
    assert tracks[0].sampling_frequency == 8000.0
    assert (tracks[0].channels, tracks[0].bit_depth) == (1, 16)

    blocks = [e for e in events if isinstance(e, mkv.Block)]
    assert [(blk.track, blk.timecode) for blk in blocks] == [(1, 1000), (2, 1000), (1, 1020), (1, 1040)]
    assert blocks[2].timecode_ns == 1_020_000_000
    assert blocks[0].keyframe
    from_customer = b"".join(blk.payload for blk in blocks if blk.track == 1)
    assert from_customer == b.pcm(480)

    tags = [(e.name, e.value) for e in events if isinstance(e, mkv.SimpleTag)]
    assert ("ContactId", "c-1") in tags
    assert tags[-1] == ("AWS_KINESISVIDEO_FRAGMENT_NUMBER", "91343852333181432392682062606740271849390003052")

    # The second fragment's events come after its own header, so per-fragment grouping works.
    second = kinds.index("Header", 1)
    assert all(not isinstance(e, mkv.Block) or e.timecode == 1040 for e in events[second:])
    clusters = [e.timecode for e in events if isinstance(e, mkv.ClusterStart)]
    assert clusters == [1000, 1040]


def test_negative_relative_timecode():
    data = b.fragment(500, [(1, -20, b"\x00\x00")], {})
    blk = next(e for e in mkv.read_events(io.BytesIO(data)) if isinstance(e, mkv.Block))
    assert blk.timecode == 480


def test_vint_sizes():
    assert mkv.read_vint(b"\x81") == (1, 1)
    assert mkv.read_vint(b"\x40\x02") == (2, 2)
    assert mkv.read_vint(b"\xff") == (-1, 1)  # all ones = unknown size
    assert mkv.read_vint(b.UNKNOWN_SIZE) == (-1, 8)
    for n in (0, 126, 127, 16382, 2**20, 2**40):
        assert mkv.read_vint(b.size(n)) == (n, len(b.size(n)))
    with pytest.raises(mkv.MkvError):
        mkv.read_vint(b"\x00")


def test_lacing_variants():
    frames = [b"a" * 3, b"b" * 300, b"c" * 5]
    hdr = b.size(1) + struct.pack(">hB", 0, 0x80 | (1 << 1))
    xiph = hdr + bytes([2]) + bytes([3]) + bytes([255, 45]) + b"".join(frames)
    assert mkv.parse_block(xiph)[3] == frames

    hdr = b.size(1) + struct.pack(">hB", 0, 0x80 | (3 << 1))
    # EBML lacing: first size 3, then signed delta +297 (two-byte vint, bias 8191)
    delta = (297 + 8191) | 0x4000
    ebml = hdr + bytes([2]) + b.size(3) + delta.to_bytes(2, "big") + b"".join(frames)
    assert mkv.parse_block(ebml)[3] == frames

    hdr = b.size(1) + struct.pack(">hB", 0, 0x80 | (2 << 1))
    fixed = hdr + bytes([2]) + b"x" * 4 + b"y" * 4 + b"z" * 4
    assert mkv.parse_block(fixed)[3] == [b"x" * 4, b"y" * 4, b"z" * 4]

    with pytest.raises(mkv.MkvError):
        mkv.parse_block(hdr + bytes([2]) + b"x" * 4)  # 4 bytes do not split into 3 frames


def test_truncated_stream_raises_after_complete_events():
    data = two_fragments()
    events = []
    with pytest.raises(mkv.TruncatedError):
        for e in mkv.read_events(io.BytesIO(data[:-7])):
            events.append(e)
    assert sum(isinstance(e, mkv.Header) for e in events) == 2


def test_rejects_absurd_leaf_size():
    data = b.EBML_HEADER + b.open_el(mkv.SEGMENT) + b.open_el(mkv.CLUSTER) + b.eid(mkv.SIMPLE_BLOCK) + b.size(mkv.MAX_LEAF_BYTES + 1)
    with pytest.raises(mkv.MkvError, match="claims"):
        list(mkv.read_events(io.BytesIO(data)))


def test_large_skipped_elements_do_not_break_offsets():
    junk = b.el(0xEC, b"\x00" * (3 << 20))  # 3 MiB Void, crosses the buffer compaction threshold
    data = b.EBML_HEADER + b.open_el(mkv.SEGMENT) + junk + b.open_el(mkv.CLUSTER) + b.uint(mkv.TIMECODE, 7) + b.simple_block(1, 0, b"\x01\x02")
    blocks = [e for e in mkv.read_events(io.BytesIO(data)) if isinstance(e, mkv.Block)]
    assert [(x.timecode, x.payload) for x in blocks] == [(7, b"\x01\x02")]
