"""IndiaCall call simulator: real audio through the real engine, end to end.

Each simulated call opens the caller websocket, streams 8 kHz mu-law in real time, plays
the agent's part over the REST API (identify, log request, liveness challenge, send app
approval, try to make the change) and plays the real customer's phone with a software
passkey. Attack calls never hold the customer's passkey; the real customer declines.

    # engine must run with COUNTERSIGN_EVAL=1 so challenges can be fixed to recorded items
    python -m ml.eval.indiacall_sim --run test --per-level 40 --genuine 40 --concurrency 2

Timing note: reply delays are sampled (genuine: from data/indiacall/human_lags.json, which
live calls fill in; attackers: from the attack model below). Audio, words, codecs, scoring,
policy and signatures are all real. The metrics page says so.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import quote

import httpx
import numpy as np
import websockets
from webauthn.helpers import bytes_to_base64url

from engine.audio.codec import mulaw_encode, resample
from engine.indiacall import OPENINGS, challenges
from ml.augment.telephony import load_audio
from ml.eval.soft_authenticator import SoftAuthenticator

DATA = Path(__file__).resolve().parents[2] / "data" / "indiacall"
REC = DATA / "recordings"
CLONES = DATA / "clones"
OUT = Path(__file__).resolve().parents[2] / "models" / "eval"

REGISTERED = "+919845012210"  # Rahul's registered number in the mock bank
OTHER = "+917000012345"
FRAME = 160  # 20 ms at 8 kHz
TTS_GENERATORS = ["xtts", "f5", "indicf5", "chatterbox"]
LEVELS = {
    "L1": "Plays pre-made clone clips",
    "L2": "Types replies into a TTS tool",
    "L3": "Converts their voice live (Seed-VC)",
    "L4": "L3 plus spoofed caller ID and a SIM swap",
}


@dataclass
class Plan:
    id: str
    level: str  # genuine | L1..L4
    speaker: str
    opening: str
    challenge: str
    generator: str
    cli: str
    lag: float
    sim_swap: bool = False


@dataclass
class Result:
    plan: dict
    language: str
    final_tier: str | None = None
    first_tier_s: float | None = None
    tiers_seen: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    liveness: dict | None = None
    features: dict | None = None
    request_status: str | None = None
    executed: bool = False
    error: str | None = None
    window_p: list[float] = field(default_factory=list)


def speakers() -> list[str]:
    return sorted(p.name for p in REC.iterdir() if p.is_dir()) if REC.exists() else []


def have(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 1000


def human_lags() -> list[float]:
    p = DATA / "human_lags.json"
    if p.exists():
        return [float(x) for x in json.loads(p.read_text())]
    return []


def sample_human_lag(rng: random.Random, measured: list[float]) -> float:
    if measured:
        return rng.choice(measured)
    return float(np.clip(rng.lognormvariate(-0.45, 0.35), 0.3, 1.6))  # placeholder until live lags exist


def build_plans(n_per_level: int, n_genuine: int, seed: int) -> list[Plan]:
    rng = random.Random(seed)
    spk = speakers()
    if not spk:
        raise SystemExit("No IndiaCall recordings yet (data/indiacall/recordings/<speaker>/).")
    ch_ids = list(challenges())
    op_ids = [o[0] for o in OPENINGS]
    measured = human_lags()
    plans: list[Plan] = []

    def pick(speaker: str, gen_dir: Path | None) -> tuple[str, str] | None:
        base = gen_dir if gen_dir else REC / speaker
        ops = [o for o in op_ids if have(base / f"{o}.wav")]
        chs = [c for c in ch_ids if have((REC / speaker if gen_dir is None else base) / f"{c}.wav")]
        if not ops or not chs:
            return None
        return rng.choice(ops), rng.choice(chs)

    for i in range(n_genuine):
        s = spk[i % len(spk)]
        p = pick(s, None)
        if p:
            plans.append(Plan(f"G{i:03d}", "genuine", s, p[0], p[1], "human", REGISTERED if rng.random() < 0.8 else OTHER, sample_human_lag(rng, measured)))
    for level in ["L1", "L2", "L3", "L4"]:
        for i in range(n_per_level):
            s = spk[i % len(spk)]
            if level in ("L1", "L2"):
                gens = [g for g in TTS_GENERATORS if (CLONES / g / s).exists()]
                if not gens:
                    continue
                g = gens[i % len(gens)]
                base = CLONES / g / s
                ops = [o for o in op_ids if have(base / f"{o}.wav")]
                if not ops:
                    continue
                if level == "L1":
                    # replay attacker can't answer an unseen challenge: plays a generic pre-made clip
                    fillers = [f.stem for f in base.glob("P0*.wav")] or ops
                    plans.append(Plan(f"{level}-{i:03d}", level, s, rng.choice(ops), rng.choice(ch_ids) + ":" + rng.choice(fillers), g, OTHER, rng.uniform(0.8, 3.0)))
                else:
                    chs = [c for c in ch_ids if have(base / f"{c}.wav")]
                    if not chs:
                        continue
                    c = rng.choice(chs)
                    typing = len(challenges()[c].say.split(": ", 1)[1]) / rng.uniform(3.0, 5.0)  # chars per second
                    plans.append(Plan(f"{level}-{i:03d}", level, s, rng.choice(ops), c, g, OTHER, typing + rng.uniform(0.4, 1.5)))
            else:
                base = CLONES / "seedvc" / s
                if not base.exists():
                    continue
                p = pick(s, base)
                if not p:
                    continue
                lag = sample_human_lag(rng, measured) + rng.uniform(0.25, 0.6)  # conversion latency
                plans.append(Plan(f"{level}-{i:03d}", level, s, p[0], p[1], "seedvc", REGISTERED if level == "L4" else OTHER, lag, sim_swap=level == "L4"))
    return plans


def audio_for(plan: Plan, item: str) -> np.ndarray:
    if plan.level == "genuine":
        path = REC / plan.speaker / f"{item}.wav"
    elif plan.level in ("L1", "L2"):
        path = CLONES / plan.generator / plan.speaker / f"{item}.wav"
    else:
        path = CLONES / "seedvc" / plan.speaker / f"{item}.wav"
    x = load_audio(str(path))
    return x / (np.max(np.abs(x)) + 1e-9) * 0.6


async def stream(ws, x16k: np.ndarray, pings: asyncio.Queue | None = None) -> None:
    """Send audio as 20 ms mu-law frames at real-time pace."""
    x8 = resample(x16k, 16000, 8000)
    n = len(x8) // FRAME
    t0 = time.perf_counter()
    for i in range(n):
        await ws.send(mulaw_encode(x8[i * FRAME : (i + 1) * FRAME]))
        delay = t0 + (i + 1) * 0.02 - time.perf_counter()
        if delay > 0:
            await asyncio.sleep(delay)


async def silence(ws, seconds: float) -> None:
    await stream(ws, np.zeros(int(seconds * 16000), dtype=np.float32) + np.random.default_rng().normal(0, 1e-4, int(seconds * 16000)).astype(np.float32))


async def run_call(base: str, plan: Plan, auth: SoftAuthenticator) -> Result:
    lang = next(o[1] for o in OPENINGS if o[0] == plan.opening)
    res = Result(plan=asdict(plan), language=lang)
    wsbase = base.replace("http", "ws", 1)
    async with httpx.AsyncClient(base_url=base, timeout=30) as http:
        # every simulated call is about the same account; don't let them count as repeat calls
        await http.post("/api/demo/clear-call-history", json={"customer_id": "rahul"})
        if plan.sim_swap:
            await http.post("/api/demo/sim-swap", json={"customer_id": "rahul", "on": True, "hours_ago": 5})
        try:
            async with websockets.connect(f"{wsbase}/ws/caller?cli={quote(plan.cli)}&lang={lang}", max_size=None) as ws:
                hello = json.loads(await ws.recv())
                cid = hello["id"]

                async def reader():
                    async for m in ws:
                        if isinstance(m, str):
                            e = json.loads(m)
                            if e.get("type") == "ping":
                                await ws.send(json.dumps({"type": "pong", "t": e["t"]}))

                rtask = asyncio.create_task(reader())
                await http.post(f"/api/calls/{cid}/answer")
                await http.post(f"/api/calls/{cid}/identify", json={"customer_id": "rahul"})
                action = "change_mobile" if plan.opening in ("O01", "O03", "O05") else "add_payee"
                details = {"new_mobile": "+917777000111"} if action == "change_mobile" else {"payee": "new.payee@okaxis"}
                req = (await http.post(f"/api/calls/{cid}/request", json={"action": action, "details": details})).json()
                await silence(ws, 0.4)
                await stream(ws, audio_for(plan, plan.opening))
                await silence(ws, 0.6)

                ch_id, _, filler = plan.challenge.partition(":")
                await http.post(f"/api/calls/{cid}/challenge", params={"force": ch_id})
                await silence(ws, 2.2)  # agent reads the challenge
                await http.post(f"/api/calls/{cid}/challenge/done-reading")
                await silence(ws, plan.lag)
                await stream(ws, audio_for(plan, filler or ch_id))
                await silence(ws, 1.2)
                call = None
                for _ in range(40):
                    call = (await http.get(f"/api/calls/{cid}")).json()
                    if call.get("liveness"):
                        break
                    await silence(ws, 0.3)

                # agent follows the policy for the logged request
                r = (await http.get(f"/api/requests/{req['id']}")).json()
                reqs = r["policy"]["reqs"]
                if reqs.get("standard_checks", {}).get("status") == "pending":
                    await http.post(f"/api/requests/{req['id']}/standard-checks", json={"passed": True})  # attackers hold leaked KYC
                if reqs.get("app_approval", {}).get("status") == "pending":
                    resp = await http.post(f"/api/requests/{req['id']}/send-approval")
                    if resp.status_code == 200:
                        apr = resp.json()
                        if plan.level == "genuine":
                            opts = (await http.post(f"/api/approvals/{apr['id']}/options")).json()
                            cred = auth.assert_(opts, b"rahul")
                            await http.post(f"/api/approvals/{apr['id']}/decide", json={"decision": "approve", "credential": cred})
                        else:
                            await http.post(f"/api/approvals/{apr['id']}/decide", json={"decision": "decline"})
                ex = await http.post(f"/api/requests/{req['id']}/execute")
                res.executed = ex.status_code == 200
                call = (await http.get(f"/api/calls/{cid}")).json()
                res.request_status = (await http.get(f"/api/requests/{req['id']}")).json()["status"]
                res.final_tier = call.get("tier")
                res.first_tier_s = call.get("first_tier_at")
                res.tiers_seen = [e["tier"] for e in call.get("timeline", []) if e.get("event") == "tier"]
                v = call.get("verdict") or {}
                res.reasons = v.get("reasons", [])
                res.features = v.get("features")
                res.liveness = call.get("liveness")
                res.window_p = [w["p"] for w in call.get("windows", [])]
                await http.post(f"/api/calls/{cid}/hangup")
                rtask.cancel()
        except Exception as e:
            res.error = f"{type(e).__name__}: {e}"
        finally:
            if plan.sim_swap:
                await http.post("/api/demo/sim-swap", json={"customer_id": "rahul", "on": False})
    return res


async def enrol(base: str, origin: str, rp_id: str) -> SoftAuthenticator:
    auth = SoftAuthenticator(rp_id, origin)
    async with httpx.AsyncClient(base_url=base, timeout=30, headers={"Origin": origin}) as http:
        await http.delete("/api/app/rahul/passkeys")
        opts = (await http.post("/api/app/rahul/passkey/options")).json()
        assert opts["user"]["id"] == bytes_to_base64url(b"rahul")
        cred = auth.register(opts)
        r = await http.post("/api/app/rahul/passkey/verify", json={"credential": cred, "device": "IndiaCall simulator"})
        r.raise_for_status()
    return auth


async def main_async(a) -> None:
    plans = build_plans(a.per_level, a.genuine, a.seed)
    if a.limit:
        plans = plans[: a.limit]
    print(f"{len(plans)} calls planned:", {lvl: sum(p.level == lvl for p in plans) for lvl in ["genuine", *LEVELS]})
    origin = a.base
    rp_id = httpx.URL(a.base).host
    auth = await enrol(a.base, origin, rp_id)
    sem = asyncio.Semaphore(a.concurrency)
    results: list[Result] = []

    async def one(p: Plan):
        async with sem:
            r = await run_call(a.base, p, auth)
            results.append(r)
            print(f"{p.id:8} {p.level:7} {p.speaker:8} tier={r.final_tier} executed={r.executed} {r.reasons} {r.error or ''}", flush=True)

    # SIM-swap calls flip shared state, so run them one at a time after the rest
    await asyncio.gather(*(one(p) for p in plans if not p.sim_swap))
    for p in plans:
        if p.sim_swap:
            await one(p)
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"indiacall_{a.run}.json"
    out.write_text(json.dumps({"run": a.run, "seed": a.seed, "created": time.time(), "results": [asdict(r) for r in results]}, indent=2))
    print("wrote", out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--run", default="test")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--per-level", type=int, default=40)
    ap.add_argument("--genuine", type=int, default=40)
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--limit", type=int, default=0)
    asyncio.run(main_async(ap.parse_args()))
