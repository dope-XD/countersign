"""The Countersign app's API (docs/agents/CONTRACT.md). Every route but sign-up needs the app's device token.

A person installs the app, signs up (name, mobile, language, how family checks should reach
them, and the public half of a key the phone makes in its Keystore) and forms a family. From
then on their phone reports its calls and asks "is this caller really them?" (engine/callcheck.py),
and answers the family's rings. Team phones claim the seeded Rahul and Sunita accounts with the
staff PIN.
"""

from __future__ import annotations

import random
import re
import secrets
import time
from collections import deque

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from engine import auth, callcheck
from engine.config import settings
from engine.db import db
from engine.hub import hub
from engine.mocks.world import DAY, Customer, world
from engine.stepup import devicekeys

router = APIRouter(prefix="/api/m")
files = APIRouter()

MAX_FAMILY = 6
INVITE_TTL = 600.0
SIGNUPS_PER_CLIENT = 10  # accounts one phone or address may open per 10 minutes
MOBILE_RE = re.compile(r"^\+91[6-9]\d{9}$")
TEST_RE = re.compile(r"^(\+?1)?(5555\d{6})$")  # Android emulators: +1 555 521 5554
ALLOW_TEST_NUMBERS = settings.allow_test_numbers

_signups: dict[str, deque[float]] = {}
_invites: dict[str, tuple[str, float]] = {}  # code -> (inviting customer, expiry)
_join_requests: dict[str, dict[str, dict]] = {}  # inviter -> joiner -> {"label": what the joiner calls the inviter, "at": t}


# ------------------------------------------------------------------ bodies
class Signup(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    mobile: str = Field(min_length=10, max_length=16)
    lang: str = Field(default="en", pattern="^(en|hi)$")
    check_channel: str = Field(default="ring", pattern="^(ring|notify)$")
    share_call_status: bool = False
    public_key: str = Field(min_length=40, max_length=400)
    device: str = Field(default="Android phone", max_length=80)

    @field_validator("mobile")
    @classmethod
    def _mobile(cls, v: str) -> str:
        v = re.sub(r"[\s-]", "", v)
        if ALLOW_TEST_NUMBERS and (m := TEST_RE.match(v)):
            return "+1" + m.group(2)
        if v.isdigit() and len(v) == 10:
            v = "+91" + v
        if not MOBILE_RE.match(v):
            raise ValueError("enter a 10-digit Indian mobile number")
        return v


class Claim(BaseModel):
    customer_id: str = Field(min_length=1, max_length=64)
    public_key: str = Field(min_length=40, max_length=400)
    device: str = Field(default="Team phone", max_length=80)


class Prefs(BaseModel):
    lang: str | None = Field(default=None, pattern="^(en|hi)$")
    check_channel: str | None = Field(default=None, pattern="^(ring|notify)$")
    share_call_status: bool | None = None


class Join(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")
    label: str = Field(min_length=1, max_length=30)  # what I call the person who invited me


class Confirm(BaseModel):
    customer_id: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=30)  # what I call the person joining


class Decide(BaseModel):
    decision: str = Field(pattern="^(approve|decline)$")
    signature: str | None = Field(default=None, max_length=400)


# ------------------------------------------------------------------ helpers
def _me(request: Request) -> Customer:
    cid = auth.require_device(request)
    cust = world.customer(cid)
    if cust is None:
        raise HTTPException(401, "This account no longer exists. Sign up again.")
    world.app_sessions[cid] = time.time()
    return cust


def _allow_signup(client: str) -> bool:
    now = time.time()
    q = _signups.setdefault(client, deque())
    while q and q[0] < now - 600:
        q.popleft()
    if len(q) >= SIGNUPS_PER_CLIENT:
        return False
    q.append(now)
    return True


def _new_account(name: str, mobile: str) -> Customer:
    first = re.sub(r"[^a-z]", "", name.split()[0].lower()) or "user"
    cid = f"c_{secrets.token_hex(5)}"
    upi = f"{first}{random.randrange(100, 1000)}@csbank"
    while world.by_upi(upi):
        upi = f"{first}{random.randrange(100, 10000)}@csbank"
    return Customer(
        id=cid,
        name=name.strip(),
        age=40,
        city="New Delhi",
        language="en-IN",
        registered_mobile=mobile,
        account_no=f"5010099{random.randrange(10**7):07d}",
        balance=250_000.0,
        upi_id=upi,
        usual_upi_max=10_000,
        known_payees=["bses.electricity@okhdfc", "freshmart.delhi@ybl"],
        card_last4=f"{random.randrange(10**4):04d}",
    )


def _family(cust: Customer) -> list[dict]:
    out = []
    for fid, link in cust.family.items():
        f = world.customer(fid)
        if f:
            out.append(
                {
                    "id": fid,
                    "label": link.get("label") or f.first_name,
                    "name": f.name,
                    "mobile": f.registered_mobile,
                    "since": link.get("since", 0.0),
                    "online": time.time() - callcheck.seen(fid) <= callcheck.ONLINE_S,
                    "new_link": time.time() - link.get("since", 0.0) < DAY,
                }
            )
    return out


def _lang(cust: Customer) -> str:
    return "hi" if cust.language.startswith("hi") else "en"


def _me_json(cust: Customer) -> dict:
    return {
        "id": cust.id,
        "name": cust.name,
        "mobile": cust.registered_mobile,
        "lang": _lang(cust),
        "check_channel": cust.check_channel,
        "share_call_status": cust.share_call_status,
    }


# ------------------------------------------------------------------ sign-up
@router.post("/signup")
async def signup(body: Signup, request: Request) -> dict:
    if not _allow_signup(auth.client_key(request)):
        raise HTTPException(429, "Too many accounts from this phone. Use the one you have, or wait a few minutes.")
    if world.by_mobile(body.mobile):
        raise HTTPException(409, "That mobile number already has a CS Bank account. Use the phone you signed up with, or another number.")
    cust = _new_account(body.name, body.mobile)
    cust.language = f"{body.lang}-IN"
    cust.check_channel = body.check_channel
    cust.share_call_status = body.share_call_status
    world.add(cust)
    try:
        devicekeys.register_device(cust.id, body.public_key, body.device)
    except devicekeys.StepUpError:
        del world.customers[cust.id]
        db.execute("DELETE FROM customers WHERE id=?", [cust.id])
        raise
    db.audit(cust.id, "account_opened_in_app", cust.id, channel=body.check_channel, share=body.share_call_status)
    return {"token": auth.make_device_token(cust.id), "me": _me_json(cust)}


@router.post("/claim")
async def claim(body: Claim, request: Request) -> dict:
    """A team phone (or the IndiaCall simulator) takes a seeded account. Staff PIN only."""
    if not auth.is_staff(request):
        raise HTTPException(401, "staff PIN required")
    cust = world.customer(body.customer_id)
    if cust is None:
        raise HTTPException(404, "no such customer")
    devicekeys.register_device(cust.id, body.public_key, body.device)
    return {"token": auth.make_device_token(cust.id), "me": _me_json(cust)}


@router.get("/home")
async def home(request: Request) -> dict:
    cust = _me(request)
    return {
        "me": _me_json(cust),
        "family": _family(cust),
        "join_requests": [
            {"customer_id": j, "name": world.customer(j).name, "label": r["label"]} for j, r in _join_requests.get(cust.id, {}).items() if world.customer(j)
        ],
        "approvals": devicekeys.pending_for(cust.id),
        "checks": callcheck.recent(cust.id),
        "scam": callcheck.scam_for(cust.id),
    }


@router.post("/prefs")
async def prefs(body: Prefs, request: Request) -> dict:
    cust = _me(request)
    if body.lang is not None:
        cust.language = f"{body.lang}-IN"
    if body.check_channel is not None:
        cust.check_channel = body.check_channel
    if body.share_call_status is not None:
        cust.share_call_status = body.share_call_status
    world.save(cust)
    db.audit(cust.id, "prefs_changed", cust.id, lang=_lang(cust), channel=cust.check_channel, share=cust.share_call_status)
    return _me_json(cust)


# ------------------------------------------------------------------ family
@router.post("/family/invite")
async def family_invite(request: Request) -> dict:
    cust = _me(request)
    if len(cust.family) >= MAX_FAMILY:
        raise HTTPException(409, f"A family can have up to {MAX_FAMILY} people.")
    now = time.time()
    for code in [c for c, (_, exp) in _invites.items() if exp < now]:
        del _invites[code]
    code = f"{secrets.randbelow(10**6):06d}"
    while code in _invites:
        code = f"{secrets.randbelow(10**6):06d}"
    _invites[code] = (cust.id, now + INVITE_TTL)
    return {"code": code, "expires_in": INVITE_TTL, "qr": f"csbank://family?code={code}"}


@router.post("/family/join")
async def family_join(body: Join, request: Request) -> dict:
    """Ask to join the inviter's family. Nothing is linked until the inviter confirms on their phone."""
    me = _me(request)
    entry = _invites.get(body.code)
    if entry is None or entry[1] < time.time():
        raise HTTPException(404, "That code has expired or doesn't exist. Ask for a new one.")
    inviter = world.customer(entry[0])
    if inviter is None or inviter.id == me.id:
        raise HTTPException(400, "That's your own code.")
    if inviter.id in me.family:
        raise HTTPException(409, f"You're already family with {inviter.first_name}.")
    _join_requests.setdefault(inviter.id, {})[me.id] = {"label": body.label.strip(), "at": time.time()}
    hub.publish(f"app:{inviter.id}", {"type": "family_request", "customer_id": me.id, "name": me.name})
    db.audit(me.id, "family_join_requested", inviter.id)
    return {"status": "waiting", "inviter": inviter.name}


@router.post("/family/confirm")
async def family_confirm(body: Confirm, request: Request) -> dict:
    me = _me(request)
    req = _join_requests.get(me.id, {}).pop(body.customer_id, None)
    joiner = world.customer(body.customer_id)
    if req is None or joiner is None:
        raise HTTPException(404, "No such request to join your family.")
    if len(me.family) >= MAX_FAMILY or len(joiner.family) >= MAX_FAMILY:
        raise HTTPException(409, f"A family can have up to {MAX_FAMILY} people.")
    now = time.time()
    me.family[joiner.id] = {"label": body.label.strip(), "since": now}
    joiner.family[me.id] = {"label": req["label"], "since": now}
    world.save(me)
    world.save(joiner)
    db.audit(me.id, "family_linked", joiner.id)
    hub.publish(f"app:{joiner.id}", {"type": "family_joined", "customer_id": me.id, "name": me.name})
    return {"family": _family(me)}


@router.post("/family/decline/{joiner}")
async def family_decline(joiner: str, request: Request) -> dict:
    me = _me(request)
    _join_requests.get(me.id, {}).pop(joiner, None)
    return {"ok": True}


@router.delete("/family/{fid}")
async def family_leave(fid: str, request: Request) -> dict:
    me = _me(request)
    other = world.customer(fid)
    me.family.pop(fid, None)
    world.save(me)
    if other:
        other.family.pop(me.id, None)
        world.save(other)
    db.audit(me.id, "family_unlinked", fid)
    return {"family": _family(me)}


# ------------------------------------------------------------------ approvals
@router.post("/approvals/{aid}/decide")
async def decide(aid: str, body: Decide, request: Request) -> dict:
    me = _me(request)
    a = devicekeys.public_approval(aid)
    if a["target_customer"] != me.id:
        raise HTTPException(403, "this approval is for someone else's phone")
    a = devicekeys.decide(aid, body.decision, body.signature)
    if a["kind"] == "call_check":
        callcheck.on_ring_decision(a)
    elif a["kind"] == "app_approval":
        from engine import approvals  # the contact-centre side: approve or decline a change asked for on a call

        approvals.on_decision(a)
    return a


# ------------------------------------------------------------------ the APK
@files.get("/download/cs-bank.apk", include_in_schema=False)
async def download_apk():
    p = settings.app_dir / "cs-bank.apk"
    if not p.is_file():
        raise HTTPException(404, "The CS Bank app isn't on this server yet.")
    return FileResponse(p, media_type="application/vnd.android.package-archive", filename="cs-bank.apk")
