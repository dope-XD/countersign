import io
import json
import struct
import wave

import pytest

from integrations.connect import kvs_dump, mkv
from integrations.connect.tests import mkvbuild as b

FRAG = "AWS_KINESISVIDEO_FRAGMENT_NUMBER"


def call_stream(codec: str = "A_PCM/INT/LIT") -> bytes:
    # Two 40 ms fragments for contact c-1 (customer track gets 2x160 samples each), then one from the next call on the pooled stream.
    out = b""
    for i, contact in enumerate(["c-1", "c-1", "c-2"]):
        tc = 1000 + 40 * i
        tags = {
            FRAG: f"9000{i}",
            "AWS_KINESISVIDEO_PRODUCER_TIMESTAMP": f"{100 + 0.04 * i:.3f}",
            "AWS_KINESISVIDEO_SERVER_TIMESTAMP": f"{100.3 + 0.04 * i:.3f}",
            "AWS_KINESISVIDEO_MILLIS_BEHIND_NOW": "120",
            "ContactId": contact,
        }
        blocks = [(1, 0, b.pcm(160, 320 * i)), (2, 0, b.pcm(320)), (1, 20, b.pcm(160, 320 * i + 160))]
        out += b.fragment(tc, blocks, tags, codec=codec)
    return out


class Clock:
    """Each call advances 10 ms from t=100.5."""

    def __init__(self):
        self.t = 100.5

    def __call__(self):
        self.t += 0.01
        return self.t


def test_parse_kvs_timestamp():
    assert kvs_dump.parse_kvs_timestamp("1571360125.131") == pytest.approx(1571360125.131)
    assert kvs_dump.parse_kvs_timestamp("1571360125131") == pytest.approx(1571360125.131)
    assert kvs_dump.parse_kvs_timestamp(b"12.5") == 12.5
    assert kvs_dump.parse_kvs_timestamp("nope") is None
    assert kvs_dump.parse_kvs_timestamp(None) is None


def test_dumper_stops_at_next_contact_and_writes_wavs(tmp_path):
    dumper = kvs_dump.Dumper(contact_id="c-1", clock=Clock())
    reason = dumper.consume(mkv.read_events(io.BytesIO(call_stream())))
    assert reason == "contact changed to c-2"
    assert [f.number for f in dumper.fragments] == ["90000", "90001"]
    assert dumper.skipped_fragments == ["90002"]

    wavs = dumper.write_wavs(tmp_path)
    assert sorted(p.name for p in wavs.values()) == ["AUDIO_FROM_CUSTOMER.wav", "AUDIO_TO_CUSTOMER.wav"]
    with wave.open(str(wavs[1])) as w:
        assert (w.getframerate(), w.getsampwidth(), w.getnchannels()) == (8000, 2, 1)
        assert w.readframes(w.getnframes()) == b.pcm(640)  # contiguous across fragments, nothing from c-2

    report = dumper.report(wavs)
    assert report["tracks"][0]["seconds"] == 0.08
    assert report["tracks"][0]["gaps_over_20ms"] == 0
    rec = report["fragments"][0]
    assert rec["audio_ms"] == 40.0
    assert rec["server_minus_producer_ms"] == pytest.approx(300.0)
    assert rec["millis_behind_now"] == 120.0
    assert rec["last_sample_lag_ms"] is not None
    assert report["summary"]["contact_ids"] == ["c-1"]
    json.dumps(report)  # must serialise


def test_without_contact_filter_keeps_everything():
    dumper = kvs_dump.Dumper(clock=Clock())
    assert dumper.consume(mkv.read_events(io.BytesIO(call_stream()))) == "end of stream"
    assert len(dumper.fragments) == 3


def test_gap_detection():
    data = b.fragment(1000, [(1, 0, b.pcm(160)), (1, 100, b.pcm(160))], {FRAG: "1"})  # 80 ms hole after a 20 ms block
    dumper = kvs_dump.Dumper(clock=Clock())
    dumper.consume(mkv.read_events(io.BytesIO(data)))
    assert dumper.tracks[1].gaps == 1
    assert dumper.tracks[1].max_gap_ms == pytest.approx(80.0)


def test_big_endian_pcm_is_swapped(tmp_path):
    be = struct.pack(">3h", 1, -2, 300)
    data = b.fragment(0, [(1, 0, be)], {FRAG: "1"}, codec="A_PCM/INT/BIG")
    dumper = kvs_dump.Dumper(clock=Clock())
    dumper.consume(mkv.read_events(io.BytesIO(data)))
    wavs = dumper.write_wavs(tmp_path)
    with wave.open(str(wavs[1])) as w:
        assert w.readframes(3) == struct.pack("<3h", 1, -2, 300)


def test_kvs_error_tag_is_reported():
    data = b.fragment(0, [], {"AWS_KINESISVIDEO_ERROR_CODE": "4500 access denied for KMS key", "AWS_KINESISVIDEO_ERROR_ID": "4500"})
    dumper = kvs_dump.Dumper(clock=Clock())
    dumper.consume(mkv.read_events(io.BytesIO(data)))
    assert len(dumper.errors) == 2


def test_idle_timeout_ends_cleanly():
    class ReadTimeoutError(Exception):  # stands in for botocore's
        pass

    def events():
        yield from mkv.read_events(io.BytesIO(call_stream()))
        raise ReadTimeoutError("read timed out")

    dumper = kvs_dump.Dumper(clock=Clock())
    assert dumper.consume(events()) == "idle: ReadTimeoutError"
    assert len(dumper.fragments) == 3


def test_truncated_stream_keeps_complete_fragments():
    dumper = kvs_dump.Dumper(clock=Clock())
    assert dumper.consume(mkv.read_events(io.BytesIO(call_stream()[:-7]))).startswith("stream truncated")
    assert len(dumper.fragments) == 3  # the cut one is closed with what arrived


def test_other_errors_propagate():
    def events():
        yield mkv.Header(0)
        raise RuntimeError("bug")

    with pytest.raises(RuntimeError):
        kvs_dump.Dumper(clock=Clock()).consume(events())


def test_start_selector_and_region():
    p = kvs_dump.build_parser()
    arn = "arn:aws:kinesisvideo:ap-southeast-1:111111111111:stream/countersign-contact-abc/1700000000000"
    assert kvs_dump.region_from_arn(arn) == "ap-southeast-1"
    assert kvs_dump.region_from_arn("arn:aws:kinesisvideo::eu-west-2:1:stream/x/1") is None

    sel = kvs_dump.start_selector(p.parse_args(["--stream-arn", arn, "--start-fragment", "913438"]))
    assert sel == {"StartSelectorType": "FRAGMENT_NUMBER", "AfterFragmentNumber": "913438"}
    sel = kvs_dump.start_selector(p.parse_args(["--stream-arn", arn, "--start-timestamp", "1571360125131", "--timestamp-type", "server"]))
    assert sel["StartSelectorType"] == "SERVER_TIMESTAMP"
    assert sel["StartTimestamp"].timestamp() == pytest.approx(1571360125.131)
    assert kvs_dump.start_selector(p.parse_args(["--stream-arn", arn])) == {"StartSelectorType": "NOW"}


def test_main_replays_saved_mkv(tmp_path):
    src = tmp_path / "stream.mkv"
    src.write_bytes(call_stream())
    out = tmp_path / "out"
    assert kvs_dump.main(["--from-file", str(src), "--out", str(out), "--contact-id", "c-1"]) == 0
    report = json.loads((out / "fragments.json").read_text(encoding="utf-8"))
    assert report["stop_reason"] == "contact changed to c-2"
    assert report["summary"]["fragments"] == 2
    assert (out / "AUDIO_FROM_CUSTOMER.wav").exists()
