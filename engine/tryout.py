"""Judges try Countersign on their own phones: /try.

One QR code opens /try. The page gets the judge a private sandbox customer (their own
account, logged in on that phone) and a softphone. A virtual agent answers the call and does
what a contact-centre agent would: hears the caller out, logs a risky request (change the
registered mobile number) and works the policy. It asks for the liveness phrase when the tier
calls for it and sends the app approval to the judge's phone. Everything else is the real
engine: the same scoring, policy, passkeys and cases as the scripted demo. Only the agent is
automatic. Its lines are spoken by the judge's phone (speech synthesis), with the mic muted
meanwhile so the agent's voice never reaches the detector.

Rahul and Sunita stay for the scripted demo. Sandboxes survive "Reset demo world".
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import secrets
import time
from collections import deque
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse

from engine import approvals, auth, policy
from engine.config import settings
from engine.db import db
from engine.hub import hub
from engine.mocks.world import SANDBOX_PREFIX, Customer, world
from engine.session import CallSession

log = logging.getLogger(__name__)
router = APIRouter()

MAX_SANDBOXES = 300
STARTS_PER_CLIENT = 10  # sandboxes one phone or address may create per 10 minutes
FIRST_TIER_WAIT_S = 30.0
LIVENESS_WAIT_S = 16.0
DECISION_WAIT_S = 180.0
BLOCKERS = {"cooloff_24h", "fraud_desk", "alert_customer"}  # requirements the caller can't meet on the call
_starts: dict[str, deque[float]] = {}
_made = 0  # sandboxes created since start, for the display name

Send = Callable[[dict], Awaitable[object]]


def is_sandbox(customer_id: str) -> bool:
    return customer_id.startswith(SANDBOX_PREFIX)


def _new_mobile() -> str:
    while True:
        m = f"+9199{random.randrange(10**8):08d}"
        if world.by_mobile(m) is None:
            return m


def create_sandbox() -> Customer:
    sandboxes = [k for k in world.customers if is_sandbox(k)]
    for old in sandboxes[: max(0, len(sandboxes) - MAX_SANDBOXES + 1)]:  # oldest first (dicts keep insertion order)
        del world.customers[old]
    global _made
    _made += 1
    n = _made
    # Random, never reused: login cookies outlive an engine restart, so an id must never come back for someone else.
    cid = f"{SANDBOX_PREFIX}{secrets.token_hex(5)}"
    mobile = _new_mobile()
    cust = Customer(
        id=cid,
        name=f"Judge {n}",
        age=45,
        city="New Delhi",
        language="en-IN",
        registered_mobile=mobile,
        account_no=f"5010099{random.randrange(10**7):07d}",
        balance=250_000.0,
        upi_id=f"judge{n}@cbank",
        usual_upi_max=10_000,
        known_payees=["electricity.bses@okhdfc", "grocer.delhi@ybl"],
        family_circle=[cid],  # on /try the family check comes back to the judge's own phone
    )
    world.customers[cid] = cust
    return cust


def _allow_start(client: str) -> bool:
    now = time.time()
    q = _starts.setdefault(client, deque())
    while q and q[0] < now - 600:
        q.popleft()
    if len(q) >= STARTS_PER_CLIENT:
        return False
    q.append(now)
    return True


def samples() -> list[dict]:
    """Cloned-voice clips a judge can play into a call: try/samples/*.wav, labelled by try/samples/labels.json."""
    d = settings.try_dir / "samples"
    if not d.is_dir():
        return []
    labels_file = d / "labels.json"
    labels = json.loads(labels_file.read_text(encoding="utf-8")) if labels_file.exists() else {}
    out = []
    for f in sorted(d.glob("*.wav")):
        label = labels.get(f.name) or re.sub(r"[_-]+", " ", f.stem).strip().capitalize()
        out.append({"id": f.stem, "label": label})
    return out


def _apk():
    p = settings.try_dir / "cs-bank.apk"
    return p if p.is_file() else None


# ------------------------------------------------------------------ HTTP


@router.post("/api/try/start")
async def try_start(request: Request, response: Response) -> dict:
    """A fresh sandbox customer, logged in on this phone."""
    if not _allow_start(auth.client_key(request)):
        raise HTTPException(429, "Too many demo accounts from this phone. Use the one you have, or wait a few minutes.")
    cust = create_sandbox()
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(
        auth.customer_cookie_name(cust.id), auth.make_cookie(f"customer:{cust.id}"), max_age=auth.TTL, httponly=True, samesite="lax", secure=secure
    )
    db.audit(cust.id, "sandbox_created", None)
    return {"customer": cust.__dict__}


@router.get("/api/try/info")
async def try_info() -> dict:
    return {"samples": samples(), "apk": _apk() is not None}


@router.get("/api/try/samples/{sid}")
async def try_sample(sid: str):
    if not re.fullmatch(r"[\w.-]+", sid) or not any(s["id"] == sid for s in samples()):
        raise HTTPException(404, "no such sample")
    return FileResponse(settings.try_dir / "samples" / f"{sid}.wav", media_type="audio/wav")


@router.get("/download/cs-bank.apk", include_in_schema=False)
async def download_apk():
    p = _apk()
    if p is None:
        raise HTTPException(404, "The CS Bank app isn't on this server yet.")
    return FileResponse(p, media_type="application/vnd.android.package-archive", filename="cs-bank.apk")


# ------------------------------------------------------------------ the virtual agent

GREETING = "Hello, you've reached Countersign Bank. I can help you change your registered mobile number. Please tell me, in a sentence or two, why you need the change."
NUDGE = "Sorry, I didn't catch that. Could you tell me a little more about why you need the change?"


class VirtualAgent:
    """Answers one /try call and works the request through the real policy, step by step."""

    def __init__(self, cs: CallSession, send: Send):
        self.cs = cs
        self.send = send
        self.rid: str | None = None

    async def say(self, text: str, **extra) -> None:
        await self.send({"type": "agent", "say": text, **extra})

    async def run(self) -> None:
        cs = self.cs
        await asyncio.sleep(1.0)
        cs.answer()  # matches the sandbox's registered number, like the IVR does
        await self.send({"type": "answered"})
        await self.say(GREETING)

        nudged = False
        t0 = time.time()
        while cs.tier is None and not cs.ended and time.time() - t0 < FIRST_TIER_WAIT_S:
            if not nudged and not cs.windows and time.time() - t0 > 20:  # nothing scoreable yet (a clip may still be starting)
                nudged = True
                await self.say(NUDGE)
            await asyncio.sleep(0.25)
        if cs.ended or cs.customer_id is None:
            return
        if cs.tier is None:  # nothing scoreable reached us: don't act on a call nobody heard
            await self.send({"type": "result", "outcome": "unfinished", "request": None, "tier": None})
            await self.say("I couldn't hear anything, so I'll end this call. Please call again and speak for a few seconds.")
            await asyncio.sleep(6)
            if not cs.ended:
                await self.send({"type": "ended"})
                cs.end()
            return

        new_mobile = _new_mobile()
        r = policy.create_request(cs.customer_id, "contact_centre", "change_mobile", {"new_mobile": new_mobile}, cs.tier or "GREEN", cs.id)
        self.rid = r["id"]
        cs.request_ids.append(r["id"])
        if cs.tier == "RED":
            cs.ensure_case("risky_request_on_red")
        cs.recompute()
        await self.say(f"Thank you. I've logged a request to change your registered mobile number to {new_mobile}.")
        await self.work()
        await self.finish()

    async def work(self) -> None:
        """One requirement at a time, until the request is executed, declined or blocked."""
        cs, rid = self.cs, self.rid
        asked_liveness = sent_approval = False
        t0 = time.time()
        while not cs.ended and time.time() - t0 < DECISION_WAIT_S:
            r = policy.get(rid)
            if r["status"] != "open":
                return
            reqs = r["policy"]["reqs"]
            miss = policy.missing(r)
            if not miss:
                policy.execute(rid, "virtual agent")
                return
            if "standard_checks" in miss:
                policy.mark(rid, "standard_checks", "met", by="virtual agent", note="date of birth and card digits (simulated)")
                await self.say("Your date of birth and card details match. In this demo we assume an attacker knows them too.")
            elif "liveness" in miss and not asked_liveness:
                asked_liveness = True
                c = cs.issue_challenge()
                asyncio.create_task(cs.challenge_timeout(c, seconds=LIVENESS_WAIT_S))  # the phone speaks the phrase first
                await self.say(f"For your security. {c.ch.say}", challenge=c.ch.say)
                while not c.done and not cs.ended:
                    await asyncio.sleep(0.25)
                passed = bool(cs.liveness and cs.liveness.get("passed"))
                await self.say("Thank you, that matches." if passed else "That didn't match what I asked for.")
            elif "app_approval" in miss and not sent_approval and reqs.get("app_approval", {}).get("status") == "pending":
                sent_approval = True
                approvals.send_app_approval(rid, require_passkey=False)
                cs.recompute()
                await self.say("I've sent an approval request to the phone registered on your account. Please answer it on your phone.")
            else:
                waiting = reqs.get("app_approval", {}).get("status") == "sent"
                stuck = BLOCKERS | ({"liveness"} if reqs.get("liveness", {}).get("status") == "failed" else set())
                if not waiting and set(miss) <= stuck:
                    return  # blocked: nothing more the caller can do on this call
            await asyncio.sleep(0.5)

    async def finish(self) -> None:
        cs = self.cs
        r = policy.get(self.rid)
        miss = policy.missing(r)
        if r["status"] == "executed":
            outcome, line = "executed", f"Done. Your registered mobile number is now {r['details']['new_mobile']}. It took one tap on your phone."
        elif r["status"] == "declined":
            outcome, line = "declined", "Thank you for telling us. Nothing was changed, and our fraud team has the case."
        elif "cooloff_24h" in miss or "fraud_desk" in miss:
            outcome, line = "held", "Because this call looked risky, the change is on hold for 24 hours and our fraud team will call your registered number."
        elif r["policy"]["reqs"].get("liveness", {}).get("status") == "failed":
            outcome, line = "held", "The voice check didn't pass, so we can't make this change on a call. Please visit a branch or use video-KYC."
        else:
            outcome, line = "unfinished", "We couldn't finish this on the call, so nothing was changed."
        await self.send({"type": "result", "outcome": outcome, "request": {**r, "missing": miss}, "tier": cs.tier})
        await self.say(line)
        await asyncio.sleep(8)
        if not cs.ended:
            await self.send({"type": "ended"})
            cs.end()


def start_virtual_agent(cs: CallSession, send: Send) -> asyncio.Task:
    """Run the virtual agent for this call, and stream the live verdict to the judge's screen."""

    async def main() -> None:
        q = hub.subscribe(f"call:{cs.id}")

        async def pump() -> None:
            while True:
                msg = await q.get()
                if json.loads(msg).get("type") in ("state", "window", "liveness"):
                    await send({"type": "verdict", "event": json.loads(msg)})

        pump_task = asyncio.create_task(pump())
        try:
            await VirtualAgent(cs, send).run()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("virtual agent failed on %s", cs.id)
            await send({"type": "agent", "say": "Sorry, something went wrong on our side. Please call again."})
        finally:
            pump_task.cancel()
            hub.unsubscribe(q)

    return asyncio.create_task(main())
