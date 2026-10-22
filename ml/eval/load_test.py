"""How many live calls one engine (one GPU) carries: N simultaneous calls through /ws/caller.

Each call streams continuous speech (same clips as ml/eval/first_tier.py) from the moment
the agent answers, at real-time pace in 20 ms G.711 frames, deadline-paced. Call starts are
spread over one 2 s hop so windows arrive the way independent calls would, not all at once.
For each N it reports, from the engine's own `window` events:

  window ms   S1 time per window as the call saw it (queue + GPU), the number in /api/health
  lag         audio time of the window -> its event on the wire: S1 + S2 + thread pool + event loop
  windows     scored per call vs. expected; a call skips a window while its last one is still scoring
  first tier  first_tier_at, seconds from answer

    .venv\\Scripts\\python -m uvicorn engine.app:app --port 8000      # with COUNTERSIGN_MAX_CALLS=40
    python -m ml.eval.load_test --ns 1,4,8,16,32 --tag rtx5070-laptop --usd-per-hour 0.0

The engine refuses calls beyond COUNTERSIGN_MAX_CALLS (default 4), so raise it above the
largest N first. Results go to models/eval/load_<tag>.json. Capacity = the largest N whose
window p95 stays under --budget-ms (300) with no windows skipped.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import random
import shutil
import subprocess
import time

import httpx
import numpy as np
import websockets

from engine.audio.codec import mulaw_encode, resample
from engine.auth import HEADER as STAFF_HEADER
from engine.auth import staff_pin
from engine.config import settings
from ml.eval.first_tier import FRAME, ROOT, continuous_speech

HOP_S = settings.hop_seconds
WINDOW_S = settings.window_samples / settings.sample_rate  # 4.04 s: the first window lands at 4.04 s of audio


class Busy(Exception):
    pass


async def one_call(base: str, cli: str, x16k: np.ndarray, delay: float) -> dict:
    await asyncio.sleep(delay)
    wsbase = base.replace("http", "ws", 1)
    hdr = {STAFF_HEADER: staff_pin()}
    wins: list[dict] = []
    t0 = 0.0
    async with (
        httpx.AsyncClient(base_url=base, timeout=30, headers=hdr) as http,
        websockets.connect(f"{wsbase}/ws/caller?cli={cli}&lang=en", max_size=None) as ws,
    ):
        first = json.loads(await ws.recv())
        if first.get("type") == "busy":
            raise Busy(first.get("message"))
        cid = first["id"]
        async with websockets.connect(f"{wsbase}/ws/events?topics=call:{cid}", additional_headers=hdr, max_size=None) as ev:

            async def caller_reader():
                async for m in ws:
                    if isinstance(m, str) and json.loads(m).get("type") == "ping":
                        await ws.send(json.dumps({"type": "pong", "t": json.loads(m)["t"]}))

            async def events():
                async for m in ev:
                    e = json.loads(m)
                    if e["type"] == "window":
                        now = time.perf_counter() - t0
                        wins.append({"t": e["t"], "ms": e["ms"], "lag_ms": round((now - e["t"]) * 1000, 1)})

            rtask = asyncio.create_task(caller_reader())
            etask = asyncio.create_task(events())
            await asyncio.sleep(0.3)  # let the event subscription settle
            await http.post(f"/api/calls/{cid}/answer")
            x8 = resample(x16k, 16000, 8000)
            t0 = start = time.perf_counter()
            for i in range(len(x8) // FRAME):
                await ws.send(mulaw_encode(x8[i * FRAME : (i + 1) * FRAME]))
                d = start + (i + 1) * 0.02 - time.perf_counter()
                if d > 0:
                    await asyncio.sleep(d)
            fed = time.perf_counter() - start
            await asyncio.sleep(1.0)  # let the last window land
            call = (await http.get(f"/api/calls/{cid}")).json()
            await http.post(f"/api/calls/{cid}/hangup")
            rtask.cancel()
            etask.cancel()
    audio_s = len(x8) // FRAME * FRAME / 8000
    expected = int((audio_s - WINDOW_S) // HOP_S) + 1  # a window at 4 s, then every 2 s
    return {"call": cid, "first_tier_at": call["first_tier_at"], "feed_speed": round(audio_s / fed, 3), "expected": expected, "windows": wins}


async def gpu_sampler(samples: list[tuple[float, float]], stop: asyncio.Event) -> None:
    """GPU utilisation % and memory MiB every 0.5 s (local engine only; skipped without nvidia-smi)."""
    if not shutil.which("nvidia-smi"):
        return
    q = ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used", "--format=csv,noheader,nounits"]
    while not stop.is_set():
        out = await asyncio.to_thread(subprocess.run, q, capture_output=True, text=True)
        try:
            u, m = out.stdout.splitlines()[0].split(",")
            samples.append((float(u), float(m)))
        except (IndexError, ValueError):
            return
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), 0.5)


def pct(xs: list[float], q: float) -> float | None:
    return round(float(np.percentile(xs, q)), 1) if xs else None


async def run_n(a, n: int, clips: list[np.ndarray]) -> dict:
    async with httpx.AsyncClient(base_url=a.base, timeout=30, headers={STAFF_HEADER: staff_pin()}) as http:
        await http.post("/api/demo/clear-call-history", json={"customer_id": "rahul"})
    rng = random.Random(a.seed + n)
    gpu: list[tuple[float, float]] = []
    stop = asyncio.Event()
    sampler = asyncio.create_task(gpu_sampler(gpu, stop))
    t = time.perf_counter()
    res = await asyncio.gather(*(one_call(a.base, a.cli, clips[i % len(clips)], rng.uniform(0, a.stagger)) for i in range(n)), return_exceptions=True)
    wall = time.perf_counter() - t
    stop.set()
    await sampler
    busy = [r for r in res if isinstance(r, Busy)]
    if busy:
        raise SystemExit(f"\nThe engine refused {len(busy)} of {n} calls as busy. Restart it with COUNTERSIGN_MAX_CALLS={max(a.ns) + 8} (default 4).")
    errs = [r for r in res if isinstance(r, BaseException)]
    if errs:
        raise errs[0]
    ms = [w["ms"] for r in res for w in r["windows"]]
    lag = [w["lag_ms"] for r in res for w in r["windows"]]
    ft = [r["first_tier_at"] for r in res if r["first_tier_at"] is not None]
    per_call = [len(r["windows"]) for r in res]
    return {
        "n": n,
        "wall_s": round(wall, 1),
        "window_ms": {"p50": pct(ms, 50), "p95": pct(ms, 95), "max": pct(ms, 100)},
        "lag_ms": {"p50": pct(lag, 50), "p95": pct(lag, 95), "max": pct(lag, 100)},
        "first_tier_s": {"p50": pct(ft, 50), "p95": pct(ft, 95), "calls_with_tier": len(ft)},
        "windows": {"scored": sum(per_call), "expected": sum(r["expected"] for r in res), "min_per_call": min(per_call)},
        "feed_speed_min": min(r["feed_speed"] for r in res),
        "gpu": {"util_mean": round(float(np.mean([u for u, _ in gpu])), 1) if gpu else None, "mem_max_mib": max((m for _, m in gpu), default=None)},
        "calls": res,
    }


async def main_async(a) -> None:
    async with httpx.AsyncClient(base_url=a.base, timeout=10) as http:
        for _ in range(600):  # the engine loads its models in the background after start-up
            h = (await http.get("/api/health")).json()
            if "loading" not in h["models"].values():
                break
            await asyncio.sleep(1)
    print(f"engine: S1 {h['s1_version']}, models {h['models']}")
    print(f"Note: the engine takes at most COUNTERSIGN_MAX_CALLS live calls (default 4); run it with COUNTERSIGN_MAX_CALLS={max(a.ns) + 8} or more.\n")
    clips = [continuous_speech(a.label, a.seconds, a.seed + i, ROOT / a.manifest)[0] for i in range(min(max(a.ns), a.clips))]
    await one_call(a.base, a.cli, clips[0][: 8 * 16000], 0)  # warm-up: the engine's first window pays for thread and kernel start-up
    rows = []
    for n in a.ns:
        r = await run_n(a, n, clips)
        rows.append(r)
        w, lg, ft, wn = r["window_ms"], r["lag_ms"], r["first_tier_s"], r["windows"]
        print(
            f"N={n:3d}  window ms p50 {w['p50']:7.1f} p95 {w['p95']:7.1f} max {w['max']:7.1f} | lag p95 {lg['p95']:7.1f} | "
            f"windows {wn['scored']}/{wn['expected']} | first tier p95 {ft['p95']} s ({ft['calls_with_tier']}/{n}) | "
            f"feed {r['feed_speed_min']}x | GPU {r['gpu']['util_mean']}% {r['gpu']['mem_max_mib']} MiB"
        )
        await asyncio.sleep(a.pause)
    ok = [
        r["n"] for r in rows if r["window_ms"]["p95"] is not None and r["window_ms"]["p95"] < a.budget_ms and r["windows"]["scored"] >= r["windows"]["expected"]
    ]
    cap = max(ok, default=0)
    summary = {
        "tag": a.tag,
        "s1_version": h["s1_version"],
        "models": h["models"],
        "health_p95_ms_after": (await httpx.AsyncClient(base_url=a.base).get("/api/health")).json()["p95_ms"],
        "budget_ms": a.budget_ms,
        "capacity_calls": cap,
        "usd_per_hour": a.usd_per_hour,
        "usd_per_call_hour": round(a.usd_per_hour / cap, 4) if a.usd_per_hour and cap else None,
        "seconds_per_call": a.seconds,
        "stagger_s": a.stagger,
        "runs": [{k: v for k, v in r.items() if k != "calls"} for r in rows],
        "calls": {r["n"]: r["calls"] for r in rows} if a.keep_calls else None,
    }
    print(f"\nOne engine carries {cap} concurrent calls with window p95 < {a.budget_ms:.0f} ms and no skipped windows.")
    if summary["usd_per_call_hour"]:
        print(f"At ${a.usd_per_hour}/h that is ${summary['usd_per_call_hour']} per call-hour.")
    out = ROOT / "models" / "eval" / f"load_{a.tag}.json"
    out.write_text(json.dumps(summary, indent=1))
    print(f"-> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--cli", default="%2B919845012210", help="Rahul's registered number, so S4 adds no flags")
    ap.add_argument("--label", default="bonafide", choices=["bonafide", "spoof"])
    ap.add_argument("--manifest", default="data/manifests/itw.csv")
    ap.add_argument("--seconds", type=float, default=20.0, help="speech per call")
    ap.add_argument("--ns", type=lambda s: [int(x) for x in s.split(",")], default=[1, 4, 8, 16, 32])
    ap.add_argument("--clips", type=int, default=8, help="distinct speakers to load (calls reuse them round-robin)")
    ap.add_argument("--stagger", type=float, default=HOP_S, help="spread call starts over this many seconds")
    ap.add_argument("--pause", type=float, default=3.0, help="seconds between steps")
    ap.add_argument("--budget-ms", type=float, default=300.0)
    ap.add_argument("--usd-per-hour", type=float, default=0.0, help="GPU price, for cost per call-hour")
    ap.add_argument("--tag", default="local")
    ap.add_argument("--keep-calls", action="store_true", help="keep every window of every call in the JSON")
    ap.add_argument("--seed", type=int, default=0)
    asyncio.run(main_async(ap.parse_args()))
