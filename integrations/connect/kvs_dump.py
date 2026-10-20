"""Pull one Amazon Connect call out of Kinesis Video Streams and write it to disk.

De-risking spike for the finale: proves the media format and measures how far
behind the live call the audio reaches us.

    python -m integrations.connect.kvs_dump --stream-arn arn:aws:kinesisvideo:... \
        --start-fragment 9134385233318150666... --contact-id 4a573372-...

Writes, into --out (default data/runtime/connect/<UTC stamp>/, which is gitignored
because it is call audio):

    AUDIO_FROM_CUSTOMER.wav, AUDIO_TO_CUSTOMER.wav   8 kHz s16le mono, one per track
    fragments.json                                   per-fragment KVS timestamps vs arrival time, plus a lag summary
    stream.mkv                                       the raw GetMedia bytes (with --save-mkv), for replay and tests

``--from-file stream.mkv`` replays a saved stream offline (no AWS, no boto3).

Needs boto3 and credentials allowed kinesisvideo:GetDataEndpoint and kinesisvideo:GetMedia
on the stream (plus kms:Decrypt on the stream's key if it is customer-managed). See README.md.
"""

from __future__ import annotations

import argparse
import array
import json
import logging
import statistics
import sys
import time
import wave
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

from integrations.connect import mkv

log = logging.getLogger("kvs_dump")

TAG_FRAGMENT_NUMBER = "AWS_KINESISVIDEO_FRAGMENT_NUMBER"
TAG_SERVER_TS = "AWS_KINESISVIDEO_SERVER_TIMESTAMP"
TAG_PRODUCER_TS = "AWS_KINESISVIDEO_PRODUCER_TIMESTAMP"
TAG_MILLIS_BEHIND = "AWS_KINESISVIDEO_MILLIS_BEHIND_NOW"
TAG_CONTINUATION = "AWS_KINESISVIDEO_CONTINUATION_TOKEN"
TAG_ERROR_CODE = "AWS_KINESISVIDEO_ERROR_CODE"
TAG_ERROR_ID = "AWS_KINESISVIDEO_ERROR_ID"
TAG_CONTACT_ID = "ContactId"

DEFAULT_REGION = "ap-southeast-1"
DEFAULT_SAMPLE_RATE = 8000
GAP_TOLERANCE_MS = 20.0


def parse_kvs_timestamp(value: str | bytes | None) -> float | None:
    """KVS timestamp tag -> epoch seconds. Accepts decimal seconds or integer milliseconds (the docs do not pin the format)."""
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    try:
        number = float(value.strip())
    except ValueError:
        return None
    return number / 1000.0 if number > 1e11 else number


def _text(value: str | bytes | None) -> str | None:
    if value is None or isinstance(value, str):
        return value
    return value.decode("utf-8", errors="replace")


@dataclass
class Fragment:
    index: int
    arrival_first: float  # wall clock when this fragment's EBML header was read
    arrival_last: float = 0.0  # wall clock when its last element was read
    tags: dict[str, str] = field(default_factory=dict)
    cluster_timecode_ms: float | None = None
    pcm: dict[int, bytearray] = field(default_factory=dict)  # track number -> bytes, committed when the fragment closes
    first_block_ms: dict[int, float] = field(default_factory=dict)

    @property
    def number(self) -> str | None:
        return self.tags.get(TAG_FRAGMENT_NUMBER)

    @property
    def contact_id(self) -> str | None:
        return self.tags.get(TAG_CONTACT_ID)


@dataclass
class TrackOut:
    info: mkv.Track
    pcm: bytearray = field(default_factory=bytearray)
    next_expected_ms: float | None = None
    gaps: int = 0
    gap_ms_total: float = 0.0
    max_gap_ms: float = 0.0

    @property
    def sample_rate(self) -> int:
        return int(self.info.sampling_frequency or DEFAULT_SAMPLE_RATE)

    @property
    def channels(self) -> int:
        return self.info.channels or 1

    @property
    def sample_width(self) -> int:
        return (self.info.bit_depth or 16) // 8

    def seconds(self, nbytes: int | None = None) -> float:
        n = len(self.pcm) if nbytes is None else nbytes
        return n / (self.sample_rate * self.channels * self.sample_width)


class Dumper:
    """Turns mkv events into per-track PCM and per-fragment timing records."""

    def __init__(self, contact_id: str | None = None, clock=time.time):
        self.contact_id = contact_id
        self.clock = clock
        self.tracks: dict[int, TrackOut] = {}
        self.fragments: list[Fragment] = []
        self.skipped_fragments: list[str | None] = []  # fragments belonging to another contact
        self.current: Fragment | None = None
        self.stop_reason = ""
        self.errors: list[dict[str, str]] = []

    # -- events -------------------------------------------------------------

    def feed(self, event: mkv.Event) -> bool:
        """Apply one event. Returns False once the stream has moved on to another contact."""
        now = self.clock()
        if isinstance(event, mkv.Header):
            if not self._close_fragment():
                return False
            self.current = Fragment(index=len(self.fragments) + len(self.skipped_fragments), arrival_first=now)
            return True
        frag = self.current
        if frag is None:  # bytes before the first EBML header: treat as one fragment anyway
            frag = self.current = Fragment(index=0, arrival_first=now)
        frag.arrival_last = now

        if isinstance(event, mkv.Track):
            if event.number not in self.tracks:
                self.tracks[event.number] = TrackOut(event)
                log.info(
                    "track %d: %s codec=%s rate=%s channels=%s bits=%s",
                    event.number,
                    event.name,
                    event.codec_id,
                    event.sampling_frequency,
                    event.channels,
                    event.bit_depth,
                )
        elif isinstance(event, mkv.ClusterStart):
            if frag.cluster_timecode_ms is None:
                frag.cluster_timecode_ms = event.timecode_ns / 1e6
        elif isinstance(event, mkv.Block):
            frag.pcm.setdefault(event.track, bytearray()).extend(event.payload)
            frag.first_block_ms.setdefault(event.track, event.timecode_ns / 1e6)
            self._note_timing(event)
        elif isinstance(event, mkv.SimpleTag):
            value = _text(event.value) or ""
            frag.tags[event.name] = value
            if event.name in (TAG_ERROR_CODE, TAG_ERROR_ID):
                self.errors.append({"fragment": frag.number or "", event.name: value})
                log.error("KVS reported %s=%s", event.name, value)
        return True

    def _note_timing(self, block: mkv.Block) -> None:
        out = self.tracks.get(block.track)
        if out is None:
            return
        start_ms = block.timecode_ns / 1e6
        if out.next_expected_ms is not None:
            gap = start_ms - out.next_expected_ms
            if gap > GAP_TOLERANCE_MS:
                out.gaps += 1
                out.gap_ms_total += gap
                out.max_gap_ms = max(out.max_gap_ms, gap)
        out.next_expected_ms = start_ms + out.seconds(len(block.payload)) * 1000.0

    def _close_fragment(self) -> bool:
        frag, self.current = self.current, None
        if frag is None:
            return True
        if self.contact_id and frag.contact_id and frag.contact_id != self.contact_id:
            # Connect pools streams: after our call ends the same stream carries the next one.
            self.skipped_fragments.append(frag.number)
            self.stop_reason = f"contact changed to {frag.contact_id}"
            log.info("fragment %s belongs to contact %s, stopping", frag.number, frag.contact_id)
            return False
        for track, data in frag.pcm.items():
            if track in self.tracks:
                self.tracks[track].pcm.extend(data)
        self.fragments.append(frag)
        rec = fragment_record(frag, self.tracks)
        log.info(
            "fragment #%d %s: %.0f ms audio, arrival-producer %s ms, behind-now %s ms",
            frag.index,
            frag.number,
            rec["audio_ms"] or 0,
            _fmt(rec["arrival_minus_producer_ms"]),
            frag.tags.get(TAG_MILLIS_BEHIND, "?"),
        )
        return True

    def consume(self, events, max_seconds: float | None = None) -> str:
        """Drain an event iterator until it ends, the contact changes, time runs out or the user hits Ctrl+C."""
        started = self.clock()
        try:
            for event in events:
                if not self.feed(event):
                    return self.stop_reason
                if max_seconds is not None and self.clock() - started > max_seconds:
                    self.stop_reason = f"max-seconds ({max_seconds:g}) reached"
                    break
            else:
                self.stop_reason = "end of stream"
        except KeyboardInterrupt:
            self.stop_reason = "interrupted"
        except mkv.TruncatedError as e:
            self.stop_reason = f"stream truncated: {e}"
        except Exception as e:  # botocore read timeouts end a live stream that went quiet
            if not _is_timeout(e):
                self._close_fragment()
                raise
            self.stop_reason = f"idle: {type(e).__name__}"
        self._close_fragment()
        return self.stop_reason

    # -- output -------------------------------------------------------------

    def write_wavs(self, out_dir: Path) -> dict[int, Path]:
        paths = {}
        for number, out in sorted(self.tracks.items()):
            if out.sample_width != 2:
                log.warning("track %d has %d-bit samples; writing them unchanged", number, out.sample_width * 8)
            data = bytes(out.pcm)
            if out.info.codec_id.upper().endswith("/BIG") and out.sample_width == 2:
                samples = array.array("h", data[: len(data) // 2 * 2])
                if sys.byteorder == "little":
                    samples.byteswap()
                data = samples.tobytes()
            elif out.info.codec_id and not out.info.codec_id.upper().startswith("A_PCM"):
                log.warning("track %d codec %s is not PCM; the WAV will be noise", number, out.info.codec_id)
            path = out_dir / f"{_safe_name(out.info.name) or f'track{number}'}.wav"
            with wave.open(str(path), "wb") as w:
                w.setnchannels(out.channels)
                w.setsampwidth(out.sample_width)
                w.setframerate(out.sample_rate)
                w.writeframes(data)
            paths[number] = path
        return paths

    def report(self, wavs: dict[int, Path] | None = None, **meta) -> dict:
        records = [fragment_record(f, self.tracks) for f in self.fragments]
        tracks = []
        for number, out in sorted(self.tracks.items()):
            tracks.append(
                {
                    "number": number,
                    "name": out.info.name,
                    "codec_id": out.info.codec_id,
                    "sample_rate": out.sample_rate,
                    "channels": out.channels,
                    "bit_depth": out.sample_width * 8,
                    "seconds": round(out.seconds(), 3),
                    "gaps_over_20ms": out.gaps,
                    "gap_ms_total": round(out.gap_ms_total, 1),
                    "max_gap_ms": round(out.max_gap_ms, 1),
                    "wav": str(wavs[number]) if wavs and number in wavs else None,
                }
            )
        summary = {
            "fragments": len(records),
            "first_fragment_number": records[0]["fragment_number"] if records else None,
            "last_fragment_number": records[-1]["fragment_number"] if records else None,
            "contact_ids": sorted({r["contact_id"] for r in records if r["contact_id"]}),
            "skipped_fragments_other_contact": len(self.skipped_fragments),
            "fragment_audio_ms": _stats([r["audio_ms"] for r in records]),
        }
        for key in ("server_minus_producer_ms", "arrival_minus_producer_ms", "arrival_minus_server_ms", "last_sample_lag_ms", "millis_behind_now"):
            summary[key] = _stats([r[key] for r in records])
        return {**meta, "stop_reason": self.stop_reason, "errors": self.errors, "tracks": tracks, "summary": summary, "fragments": records}


def fragment_record(frag: Fragment, tracks: dict[int, TrackOut]) -> dict:
    producer = parse_kvs_timestamp(frag.tags.get(TAG_PRODUCER_TS))
    server = parse_kvs_timestamp(frag.tags.get(TAG_SERVER_TS))
    audio_ms = None
    durations = [tracks[t].seconds(len(d)) * 1000.0 for t, d in frag.pcm.items() if t in tracks]
    if durations:
        audio_ms = max(durations)
    behind = frag.tags.get(TAG_MILLIS_BEHIND)

    def diff_ms(a: float | None, b: float | None) -> float | None:
        return None if a is None or b is None else round((a - b) * 1000.0, 1)

    return {
        "index": frag.index,
        "fragment_number": frag.number,
        "contact_id": frag.contact_id,
        "producer_timestamp": producer,
        "server_timestamp": server,
        "arrival_first": round(frag.arrival_first, 3),
        "arrival_last": round(frag.arrival_last, 3),
        "cluster_timecode_ms": frag.cluster_timecode_ms,
        "audio_ms": None if audio_ms is None else round(audio_ms, 1),
        "bytes_per_track": {tracks[t].info.name if t in tracks else str(t): len(d) for t, d in frag.pcm.items()},
        "millis_behind_now": float(behind) if behind and behind.replace(".", "", 1).isdigit() else None,
        # KVS ingest delay: Connect's producer clock to the KVS server clock.
        "server_minus_producer_ms": diff_ms(server, producer),
        # Fragment start to first byte on this laptop (includes the fragment's own duration).
        "arrival_minus_producer_ms": diff_ms(frag.arrival_first, producer),
        "arrival_minus_server_ms": diff_ms(frag.arrival_first, server),
        # The number the engine cares about: last sample spoken -> last byte here.
        "last_sample_lag_ms": diff_ms(frag.arrival_last, None if producer is None or audio_ms is None else producer + audio_ms / 1000.0),
        "tags": {k: v for k, v in frag.tags.items() if k != TAG_CONTINUATION},
    }


def _stats(values: list[float | None]) -> dict | None:
    xs = sorted(v for v in values if v is not None)
    if not xs:
        return None
    p95 = xs[min(len(xs) - 1, round(0.95 * (len(xs) - 1)))]
    return {"n": len(xs), "min": xs[0], "median": statistics.median(xs), "p95": p95, "max": xs[-1]}


def _fmt(v: float | None) -> str:
    return "?" if v is None else f"{v:.0f}"


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name).strip("_")


def _is_timeout(e: BaseException) -> bool:
    if isinstance(e, TimeoutError):
        return True
    return "Timeout" in type(e).__name__  # botocore.exceptions.ReadTimeoutError, urllib3 ReadTimeoutError


class Tee:
    """Readable that copies everything it reads to a file (the raw MKV, for replay)."""

    def __init__(self, source, sink: BinaryIO):
        self.source = source
        self.sink = sink

    def read(self, n: int = -1) -> bytes:
        data = self.source.read(n)
        if data:
            self.sink.write(data)
        return data


# -- AWS ----------------------------------------------------------------------


def region_from_arn(arn: str) -> str | None:
    parts = arn.split(":")
    if len(parts) > 4 and parts[2] == "kinesisvideo":
        return parts[3] or None
    return None


def start_selector(args: argparse.Namespace) -> dict:
    if args.start_fragment:
        return {"StartSelectorType": "FRAGMENT_NUMBER", "AfterFragmentNumber": str(args.start_fragment)}
    if args.start_timestamp:
        ts = datetime.fromtimestamp(float(args.start_timestamp) / 1000.0, tz=UTC)  # Connect's StartTimestamp is epoch ms
        return {"StartSelectorType": f"{args.timestamp_type.upper()}_TIMESTAMP", "StartTimestamp": ts}
    return {"StartSelectorType": args.start.upper()}


def open_get_media(stream_arn: str, selector: dict, region: str, profile: str | None, idle_timeout: float):
    import boto3  # only needed for live pulls
    from botocore.config import Config

    session = boto3.Session(profile_name=profile, region_name=region)
    endpoint = session.client("kinesisvideo").get_data_endpoint(StreamARN=stream_arn, APIName="GET_MEDIA")["DataEndpoint"]
    media = session.client(
        "kinesis-video-media",
        endpoint_url=endpoint,
        config=Config(read_timeout=idle_timeout, connect_timeout=10, retries={"max_attempts": 1}),
    )
    resp = media.get_media(StreamARN=stream_arn, StartSelector=selector)
    log.info("GetMedia %s from %s, content-type %s", selector["StartSelectorType"], endpoint, resp.get("ContentType"))
    return resp["Payload"]


# -- CLI ----------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--stream-arn", help="KVS stream ARN from the contact's MediaStreams.Customer.Audio.StreamARN")
    src.add_argument("--from-file", type=Path, help="replay a saved MKV instead of calling AWS")
    start = p.add_mutually_exclusive_group()
    start.add_argument("--start-fragment", help="MediaStreams.Customer.Audio.StartFragmentNumber (FRAGMENT_NUMBER selector)")
    start.add_argument("--start-timestamp", help="epoch milliseconds, e.g. MediaStreams.Customer.Audio.StartTimestamp")
    start.add_argument("--start", choices=["now", "earliest"], default="now", help="when no fragment/timestamp is given (default: now)")
    p.add_argument("--timestamp-type", choices=["producer", "server"], default="producer", help="clock --start-timestamp refers to")
    p.add_argument("--contact-id", help="stop when the stream moves on to a different contact (Connect reuses streams)")
    p.add_argument("--region", help=f"defaults to the ARN's region, else {DEFAULT_REGION}")
    p.add_argument("--profile", help="AWS named profile for the consumer IAM user")
    p.add_argument("--out", type=Path, help="output directory (default data/runtime/connect/<UTC stamp>)")
    p.add_argument("--max-seconds", type=float, default=900.0, help="stop after this much wall time (default 900)")
    p.add_argument("--idle-timeout", type=float, default=10.0, help="stop when no bytes arrive for this long (default 10 s)")
    p.add_argument("--chunk-bytes", type=int, default=2048, help="read size; small keeps arrival times honest (default 2048)")
    p.add_argument("--save-mkv", action="store_true", help="also save the raw GetMedia bytes as stream.mkv")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = args.out or Path("data/runtime/connect") / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    meta: dict = {"started_at": stamp}
    if args.from_file:
        source = args.from_file.open("rb")
        meta["source"] = str(args.from_file)
    else:
        region = args.region or region_from_arn(args.stream_arn) or DEFAULT_REGION
        selector = start_selector(args)
        source = open_get_media(args.stream_arn, selector, region, args.profile, args.idle_timeout)
        meta.update(stream_arn=args.stream_arn, region=region, start_selector={k: str(v) for k, v in selector.items()})
    meta["contact_id_filter"] = args.contact_id

    sink = (out_dir / "stream.mkv").open("wb") if args.save_mkv and not args.from_file else None
    reader = mkv.MkvReader(Tee(source, sink) if sink else source, chunk_size=args.chunk_bytes)
    dumper = Dumper(contact_id=args.contact_id)
    try:
        reason = dumper.consume(iter(reader), max_seconds=args.max_seconds)
    finally:
        source.close()
        if sink:
            sink.close()

    wavs = dumper.write_wavs(out_dir)
    report = dumper.report(wavs, **meta)
    (out_dir / "fragments.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    log.info("stopped: %s", reason)
    for t in report["tracks"]:
        log.info("  %s: %.1f s, %d gaps -> %s", t["name"] or t["number"], t["seconds"], t["gaps_over_20ms"], t["wav"])
    s = report["summary"]
    for key in ("last_sample_lag_ms", "arrival_minus_producer_ms", "server_minus_producer_ms", "fragment_audio_ms"):
        if s[key]:
            log.info("  %s: median %.0f, p95 %.0f, max %.0f (n=%d)", key, s[key]["median"], s[key]["p95"], s[key]["max"], s[key]["n"])
    log.info("wrote %s", out_dir / "fragments.json")
    if dumper.errors:
        return 2
    return 0 if dumper.fragments else 1


if __name__ == "__main__":
    sys.exit(main())
