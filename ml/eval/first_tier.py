"""Time to first tier on a live call, measured through the real engine.

Streams continuous speech (same-speaker In-the-Wild clips joined, silences trimmed, to
14 s) into /ws/caller from the moment the agent answers, at real-time pace in 20 ms
G.711 frames, and logs when each window was scored and when the first tier arrived.
first_tier_at is the engine's own number: seconds from answer (CallSession.answer()
resets the call clock), the same moment the agent sees the call go live.

    python -m ml.eval.first_tier --calls 10            # engine on :8000 (.\\run.ps1)
    python -m ml.eval.first_tier --label spoof --calls 10
    python -m ml.eval.first_tier --pacing sleep          # how the 20 Oct test client paced frames

Pacing matters: on Windows asyncio.sleep(0.02) takes ~31 ms (15.6 ms timer ticks), so a
client that sleeps a fixed 20 ms per frame feeds the engine at ~0.64x real time and every
window lands ~1.6x later on the wall clock. The default paces frames against a deadline
(as ml/eval/indiacall_sim.py does) and the report prints the feed speed of each call.

Target (deck): p95 first tier < 8 s.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import random
import time
from pathlib import Path

import httpx
import numpy as np
import websockets

from engine.audio.codec import mulaw_encode, resample
from engine.auth import HEADER as STAFF_HEADER
from engine.auth import staff_pin

ROOT = Path(__file__).resolve().parents[2]
FRAME = 160  # 20 ms at 8 kHz


def _trim(x: np.ndarray, sr: int, db: float = -40.0) -> np.ndarray:
    """Cut leading and trailing silence (20 ms frames below `db` relative to the clip peak)."""
    f = sr // 50
    n = len(x) // f
    if n == 0:
        return x
    rms = np.sqrt(np.mean(x[: n * f].reshape(n, f) ** 2, axis=1) + 1e-12)
    loud = np.flatnonzero(20 * np.log10(rms / (rms.max() + 1e-12)) > db)
    return x[loud[0] * f : (loud[-1] + 1) * f] if len(loud) else x


def continuous_speech(label: str, seconds: float, seed: int, manifest: Path) -> tuple[np.ndarray, str]:
    """`seconds` of 16 kHz speech from one speaker with no pauses longer than the clips' own."""
    from ml.augment.telephony import load_audio

    rows = [r for r in csv.DictReader(manifest.open()) if r["label"] == label and (ROOT / r["path"]).exists()]
    by_spk: dict[str, list[str]] = {}
    for r in rows:
        by_spk.setdefault(r["speaker"], []).append(r["path"])
    spk = sorted(s for s, p in by_spk.items() if len(p) >= 4)
    speaker = random.Random(seed).choice(spk)
    parts, n = [], 0
    for p in by_spk[speaker]:
        x = _trim(load_audio(str(ROOT / p)), 16000)
        parts.append(x / (np.max(np.abs(x)) + 1e-9) * 0.6)
        n += len(x)
        if n >= seconds * 16000:
            break
    return np.concatenate(parts)[: int(seconds * 16000)].astype(np.float32), speaker


async def one_call(base: str, cli: str, x16k: np.ndarray, pacing: str = "deadline") -> dict:
    wsbase = base.replace("http", "ws", 1)
    hdr = {STAFF_HEADER: staff_pin()}
    log: list[dict] = []
    async with httpx.AsyncClient(base_url=base, timeout=30, headers=hdr) as http:
        await http.post("/api/demo/clear-call-history", json={"customer_id": "rahul"})  # back-to-back runs aren't REPEAT_CALLS
        async with websockets.connect(f"{wsbase}/ws/caller?cli={cli}&lang=en", max_size=None) as ws:
            cid = json.loads(await ws.recv())["id"]
            async with websockets.connect(f"{wsbase}/ws/events?topics=call:{cid}", additional_headers=hdr, max_size=None) as ev:

                async def caller_reader():
                    async for m in ws:
                        if isinstance(m, str) and json.loads(m).get("type") == "ping":
                            await ws.send(json.dumps({"type": "pong", "t": json.loads(m)["t"]}))

                t0 = 0.0

                async def events():
                    async for m in ev:
                        e = json.loads(m)
                        now = time.time() - t0
                        if e["type"] == "window":
                            log.append({"wall": round(now, 2), "event": "window", "t_audio": e["t"], "p": e["p"], "ms": e["ms"]})
                        elif e["type"] == "state" and e["call"]["tier"] and not any(x["event"] == "tier" for x in log):
                            log.append({"wall": round(now, 2), "event": "tier", "tier": e["call"]["tier"], "server_first_tier_at": e["call"]["first_tier_at"]})

                rtask = asyncio.create_task(caller_reader())
                etask = asyncio.create_task(events())
                await asyncio.sleep(0.3)  # let the event subscription settle
                await http.post(f"/api/calls/{cid}/answer")
                t0 = time.time()
                x8 = resample(x16k, 16000, 8000)
                start = time.perf_counter()
                for i in range(len(x8) // FRAME):
                    await ws.send(mulaw_encode(x8[i * FRAME : (i + 1) * FRAME]))
                    if pacing == "sleep":
                        await asyncio.sleep(0.02)  # ~31 ms on Windows (15.6 ms timer): the feed runs at ~0.64x real time
                    else:
                        delay = start + (i + 1) * 0.02 - time.perf_counter()
                        if delay > 0:
                            await asyncio.sleep(delay)
                fed = time.perf_counter() - start
                await asyncio.sleep(0.5)
                call = (await http.get(f"/api/calls/{cid}")).json()
                await http.post(f"/api/calls/{cid}/hangup")
                rtask.cancel()
                etask.cancel()
    speed = len(x8) / 8000 / fed
    return {"call": cid, "first_tier_at": call["first_tier_at"], "tier": call["tier"], "model": call["model"], "feed_speed": round(speed, 3), "log": log}


async def main_async(a) -> None:
    out = []
    for i in range(a.calls):
        x, speaker = continuous_speech(a.label, a.seconds, a.seed + i, ROOT / a.manifest)
        r = await one_call(a.base, a.cli, x, a.pacing)
        r["speaker"] = speaker
        out.append(r)
        print(f"call {i + 1}: {speaker:24} first_tier_at={r['first_tier_at']:.2f} tier={r['tier']} feed={r['feed_speed']}x real time")
        for e in r["log"]:
            print("   ", e)
    ft = [r["first_tier_at"] for r in out if r["first_tier_at"] is not None]
    if ft:
        print(f"\nS1 {out[0]['model']['s1']} {out[0]['model']['version']}")
        print(f"first_tier_at over {len(ft)}/{len(out)} calls: p50 {np.percentile(ft, 50):.2f} s, p95 {np.percentile(ft, 95):.2f} s, max {max(ft):.2f} s")
    if a.out:
        Path(a.out).write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--cli", default="%2B919845012210", help="Rahul's registered number, so S4 adds no flags")
    ap.add_argument("--label", default="bonafide", choices=["bonafide", "spoof"])
    ap.add_argument("--manifest", default="data/manifests/itw.csv")
    ap.add_argument("--seconds", type=float, default=14.0)
    ap.add_argument("--calls", type=int, default=5)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument(
        "--pacing", default="deadline", choices=["deadline", "sleep"], help="sleep = a plain asyncio.sleep(0.02) per frame (reproduces the 9.5 s of 20 Oct)"
    )
    ap.add_argument("--out", default="")
    asyncio.run(main_async(ap.parse_args()))
