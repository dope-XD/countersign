"""IndiaCall call simulator: real audio through the real engine, end to end.

Each simulated call opens the caller websocket, streams 8 kHz mu-law in real time, plays
the agent's part over the REST API (identify, log request, liveness challenge, send app
approval, try to make the change) and plays the real customer's phone with a software
passkey. Attack calls never hold the customer's passkey; the real customer declines.

    # engine must run with COUNTERSIGN_EVAL=1 so challenges can be fixed to recorded items
    python -m ml.eval.indiacall_sim --run dev --dry-run      # just print the plan mix
    python -m ml.eval.indiacall_sim --run test --per-level 40 --genuine 120 --concurrency 2

Plan mix: genuine calls cycle over every speaker in data/indiacall/recordings (volunteers
who were never cloned included); most come from the registered number and the rest from a
clean, unrated spare phone (a genuine caller on a family member's phone). Attack levels
cycle over the speakers that have clones for that level. Half of L1-L3 spoof the
registered number so voice signals are measured without S4's caller-ID flags; the other
half call from a number rated High on FRI. Each result records its `cli_kind`.

Timing note: reply delays are sampled (genuine: from data/indiacall/human_lags.json, which
live calls fill in, else a placeholder distribution; attackers: from the attack model
below). Audio, words, codecs, scoring, policy and signatures are all real. The metrics
page says so.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import quote

import httpx
import numpy as np
import websockets

from engine.audio.codec import mulaw_encode, resample
from engine.auth import HEADER as STAFF_HEADER
from engine.auth import staff_pin
from engine.indiacall import OPENINGS, challenges
from engine.mocks.world import FRAUD_PHONE, FRI_SEED, SEED, SPARE_PHONE
from ml.eval.soft_device import SoftDevice

DATA = Path(__file__).resolve().parents[2] / "data" / "indiacall"
REC = DATA / "recordings"
CLONES = DATA / "clones"
OUT = Path(__file__).resolve().parents[2] / "models" / "eval"

REGISTERED = SEED["rahul"].registered_mobile  # Rahul's registered number in the mock bank
GENUINE_OTHER = SPARE_PHONE  # genuine caller on another phone: unregistered but on no fraud list
ATTACKER_OWN = FRAUD_PHONE  # attacker calling from their own number, rated High on FRI
assert GENUINE_OTHER not in FRI_SEED and ATTACKER_OWN in FRI_SEED
FRAME = 160  # 20 ms at 8 kHz
TTS_GENERATORS = ["xtts", "f5", "indicf5", "chatterbox"]
LEVELS = {
    "L1": "Plays pre-made clone clips",
    "L2": "Types replies into a TTS tool",
    "L3": "Converts their voice live (Seed-VC)",
    "L4": "L3 plus spoofed caller ID and a SIM swap",
}
CLI_KINDS = {"registered": "registered number", "other": "another number"}
PLACEHOLDER_LAG = "log-normal, median 0.64 s, clipped to 0.3-1.6 s"


def cli_kind(cli: str) -> str:
    return "registered" if cli == REGISTERED else "other"


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
    cli_kind: str = field(init=False)  # registered | other (for L1-L3, registered = spoofed caller ID)

    def __post_init__(self):
        self.cli_kind = cli_kind(self.cli)


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
    voice_tier: str | None = None  # latest tier from voice signals alone, before S4 context
    context_flags: list[str] = field(default_factory=list)
    request_status: str | None = None
    executed: bool = False
    error: str | None = None
    window_p: list[float] = field(default_factory=list)


def speakers(rec: Path | None = None) -> list[str]:
    rec = rec or REC
    return sorted(p.name for p in rec.iterdir() if p.is_dir()) if rec.exists() else []


def have(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 1000


def human_lags(data: Path | None = None) -> list[float]:
    p = (data or DATA) / "human_lags.json"
    if p.exists():
        return [float(x) for x in json.loads(p.read_text())]
    return []


def sample_human_lag(rng: random.Random, measured: list[float]) -> float:
    if measured:
        return rng.choice(measured)
    return float(np.clip(rng.lognormvariate(-0.45, 0.35), 0.3, 1.6))  # placeholder until live lags exist (PLACEHOLDER_LAG)


def _mix(rng: random.Random, n: int, share: float, yes: str, no: str) -> list[str]:
    """n items, round(share * n) of them `yes`, shuffled: an exact split rather than a coin flip per call."""
    k = round(share * n)
    out = [yes] * k + [no] * (n - k)
    rng.shuffle(out)
    return out


def build_plans(
    n_per_level: int,
    n_genuine: int,
    seed: int,
    other_share: float = 0.2,
    spoof_share: float = 0.5,
    rec: Path | None = None,
    clones: Path | None = None,
    data: Path | None = None,
) -> list[Plan]:
    """Plan the calls. Speakers without clones (genuine-only volunteers) get genuine calls only."""
    rec, clones = rec or REC, clones or CLONES
    rng = random.Random(seed)
    spk = speakers(rec)
    if not spk:
        raise SystemExit(f"No IndiaCall recordings yet ({rec}/<speaker>/).")
    ch_ids = list(challenges())
    op_ids = [o[0] for o in OPENINGS]
    measured = human_lags(data)
    plans: list[Plan] = []

    def items(base: Path) -> tuple[list[str], list[str]]:
        return [o for o in op_ids if have(base / f"{o}.wav")], [c for c in ch_ids if have(base / f"{c}.wav")]

    def usable(base: Path) -> bool:
        ops, chs = items(base)
        return bool(ops and chs)

    genuine_spk = [s for s in spk if usable(rec / s)]
    if n_genuine and not genuine_spk:
        print("no speaker has both an opening and a challenge recorded; no genuine calls planned")
    clis = _mix(rng, n_genuine, other_share, GENUINE_OTHER, REGISTERED)
    for i in range(n_genuine if genuine_spk else 0):
        s = genuine_spk[i % len(genuine_spk)]
        ops, chs = items(rec / s)
        plans.append(Plan(f"G{i:03d}", "genuine", s, rng.choice(ops), rng.choice(chs), "human", clis[i], sample_human_lag(rng, measured)))

    # TTS clones need the openings; L1 then replays a filler, L2 also needs the challenge lines
    tts = {s: [g for g in TTS_GENERATORS if items(clones / g / s)[0]] for s in spk}
    eligible = {
        "L1": [s for s in spk if tts[s]],
        "L2": [s for s in spk if any(usable(clones / g / s) for g in tts[s])],
        "L3": [s for s in spk if usable(clones / "seedvc" / s)],
    }
    eligible["L4"] = eligible["L3"]
    for level in ["L1", "L2", "L3", "L4"]:
        elig = eligible[level]
        if not elig:
            if n_per_level:
                print(f"{level}: no speaker has the clones it needs; skipped")
            continue
        # L1-L3: some spoof the registered number (isolates the voice signals), the rest use their own
        clis = _mix(rng, n_per_level, spoof_share, REGISTERED, ATTACKER_OWN) if level != "L4" else [REGISTERED] * n_per_level
        for i in range(n_per_level):
            s = elig[i % len(elig)]
            pid = f"{level}-{i:03d}"
            if level in ("L1", "L2"):
                gens = tts[s] if level == "L1" else [g for g in tts[s] if usable(clones / g / s)]
                g = gens[(i // len(elig)) % len(gens)]
                base = clones / g / s
                ops, chs = items(base)
                if level == "L1":
                    # replay attacker can't answer an unseen challenge: plays a generic pre-made clip
                    fillers = sorted(f.stem for f in base.glob("P0*.wav")) or ops
                    plans.append(Plan(pid, level, s, rng.choice(ops), rng.choice(ch_ids) + ":" + rng.choice(fillers), g, clis[i], rng.uniform(0.8, 3.0)))
                else:
                    c = rng.choice(chs)
                    typing = len(challenges()[c].say.split(": ", 1)[1]) / rng.uniform(3.0, 5.0)  # chars per second
                    plans.append(Plan(pid, level, s, rng.choice(ops), c, g, clis[i], typing + rng.uniform(0.4, 1.5)))
            else:
                ops, chs = items(clones / "seedvc" / s)
                lag = sample_human_lag(rng, measured) + rng.uniform(0.25, 0.6)  # conversion latency
                plans.append(Plan(pid, level, s, rng.choice(ops), rng.choice(chs), "seedvc", clis[i], lag, sim_swap=level == "L4"))
    return plans


def plan_summary(plans: list[Plan]) -> dict:
    return {
        "calls": dict(Counter(f"{p.level}/{p.cli_kind}" for p in plans)),
        "genuine_by_speaker": dict(Counter(p.speaker for p in plans if p.level == "genuine")),
        "attacks_by_speaker": dict(Counter(p.speaker for p in plans if p.level != "genuine")),
    }


def audio_for(plan: Plan, item: str) -> np.ndarray:
    from ml.augment.telephony import load_audio  # here so planning and reports don't need the audio stack

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


async def run_call(base: str, plan: Plan, device: SoftDevice) -> Result:
    lang = next(o[1] for o in OPENINGS if o[0] == plan.opening)
    res = Result(plan=asdict(plan), language=lang)
    wsbase = base.replace("http", "ws", 1)
    async with httpx.AsyncClient(base_url=base, timeout=30, headers={STAFF_HEADER: staff_pin()}) as http:
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
                        phone = {"X-Device-Token": device.token}
                        if plan.level == "genuine":
                            body = {"decision": "approve", "signature": device.sign(apr)}
                        else:
                            body = {"decision": "decline"}
                        await http.post(f"/api/m/approvals/{apr['id']}/decide", json=body, headers=phone)
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
                res.voice_tier = v.get("voice_tier")
                res.context_flags = (v.get("context") or {}).get("flags", [])
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


async def enrol(base: str, run: str) -> SoftDevice:
    """Add the simulator's own phone key to Rahul's account, next to the team phone's (never removes it)."""
    device = SoftDevice()
    async with httpx.AsyncClient(base_url=base, timeout=30, headers={STAFF_HEADER: staff_pin()}) as http:
        r = await http.post("/api/m/claim", json={"customer_id": "rahul", "public_key": device.public_key, "device": f"IndiaCall simulator ({run})"})
        r.raise_for_status()
        device.token = r.json()["token"]
    return device


async def reset_numbers(base: str) -> None:
    """The demo panel can re-rate numbers live; put the two the simulator relies on back to their seed."""
    async with httpx.AsyncClient(base_url=base, timeout=30, headers={STAFF_HEADER: staff_pin()}) as http:
        (await http.post("/api/demo/fri", json={"number": GENUINE_OTHER, "rating": None})).raise_for_status()
        (await http.post("/api/demo/fri", json={"number": ATTACKER_OWN, "rating": FRI_SEED[ATTACKER_OWN]})).raise_for_status()


async def main_async(a) -> None:
    lags = human_lags()  # what build_plans samples genuine reply delays from
    plans = build_plans(a.per_level, a.genuine, a.seed, other_share=a.other_share, spoof_share=a.spoof_share)
    if a.limit:
        plans = plans[: a.limit]
    print(f"{len(plans)} calls planned:", json.dumps(plan_summary(plans), indent=1))
    if a.dry_run:
        return
    await reset_numbers(a.base)
    device = await enrol(a.base, a.run)
    sem = asyncio.Semaphore(a.concurrency)
    results: list[Result] = []

    async def one(p: Plan):
        async with sem:
            r = await run_call(a.base, p, device)
            results.append(r)
            print(f"{p.id:8} {p.level:7} {p.cli_kind:10} {p.speaker:8} tier={r.final_tier} executed={r.executed} {r.reasons} {r.error or ''}", flush=True)

    # SIM-swap calls flip shared state, so run them one at a time after the rest
    await asyncio.gather(*(one(p) for p in plans if not p.sim_swap))
    for p in plans:
        if p.sim_swap:
            await one(p)
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"indiacall_{a.run}.json"
    meta = {"run": a.run, "seed": a.seed, "created": time.time(), "human_lags": {"measured": len(lags), "placeholder": None if lags else PLACEHOLDER_LAG}}
    out.write_text(json.dumps({**meta, "results": [asdict(r) for r in results]}, indent=2))
    print("wrote", out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--run", default="test")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--per-level", type=int, default=40)
    ap.add_argument("--genuine", type=int, default=120, help="spread across every recorded speaker")
    ap.add_argument("--other-share", type=float, default=0.2, help="share of genuine calls from a spare (unregistered, unrated) phone")
    ap.add_argument("--spoof-share", type=float, default=0.5, help="share of L1-L3 calls that spoof the registered number")
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true", help="print the plan mix and exit without calling the engine")
    asyncio.run(main_async(ap.parse_args()))
