"""The CS Bank Android app's API (android/). Every route but sign-up needs the app's device token.

A judge installs the app, signs up (name, mobile, how family checks should reach them, and the
public half of a key the phone makes in its Keystore), forms a family with another judge, and
from then on the app shows their account, pays, answers family checks and approvals, and
reports the phone's call state. The team's phones claim the seeded Rahul and Sunita accounts
with the staff PIN.
"""

from __future__ import annotations

import json
import random
import re
import secrets
import time
from collections import deque

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from engine import auth, callcheck, guard
from engine.config import settings
from engine.db import db
from engine.hub import hub
from engine.mocks.world import Customer, world
from engine.session import calls
from engine.stepup import devicekeys

router = APIRouter(prefix="/api/m")
files = APIRouter()

MAX_FAMILY = 6
INVITE_TTL = 600.0
SIGNUPS_PER_CLIENT = 10  # accounts one phone or address may open per 10 minutes
KILL_SWITCH_WAIT_S = 3600.0
MOBILE_RE = re.compile(r"^\+91[6-9]\d{9}$")

_signups: dict[str, deque[float]] = {}
_invites: dict[str, tuple[str, float]] = {}  # code -> (inviting customer, expiry)
_join_requests: dict[str, dict[str, dict]] = {}  # inviter -> joiner -> {"label": what the joiner calls the inviter, "at": t}


# ------------------------------------------------------------------ bodies
class Signup(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    mobile: str = Field(min_length=10, max_length=16)
    check_channel: str = Field(default="ring", pattern="^(ring|notify)$")
    share_call_status: bool = False
    public_key: str = Field(min_length=40, max_length=400)
    device: str = Field(default="Android phone", max_length=80)

    @field_validator("mobile")
    @classmethod
    def _mobile(cls, v: str) -> str:
        v = re.sub(r"[\s-]", "", v)
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
    check_channel: str | None = Field(default=None, pattern="^(ring|notify)$")
    share_call_status: bool | None = None


class Join(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")
    label: str = Field(min_length=1, max_length=30)  # what I call the person who invited me


class Confirm(BaseModel):
    customer_id: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=30)  # what I call the person joining


class CallState(BaseModel):
    state: str = Field(pattern="^(active|ended)$")
    kind: str = Field(default="phone", pattern="^(phone|internet)$")
    direction: str = Field(default="unknown", pattern="^(incoming|outgoing|unknown)$")


class Pay(BaseModel):
    payee: str = Field(min_length=3, max_length=100)
    amount: float = Field(gt=0, le=10_000_000)
    note: str = Field(default="", max_length=200)

    @field_validator("payee")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip().lower()
        if not re.fullmatch(r"[a-z0-9._-]{2,64}@[a-z0-9.-]{2,32}", v):
            raise ValueError("enter a UPI ID like name@bank")
        return v


class Asked(BaseModel):
    someone_asked: bool


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


def _bank_call(cid: str) -> dict | None:
    """The bank's live call with this customer, if any: the app shows it as a verified call."""
    for c in calls.calls.values():
        if c.customer_id == cid and not c.ended and c.source in ("app", "connect", "softphone") and c.status == "live":
            who = "CS Bank's virtual assistant" if c.source == "app" else "a CS Bank agent"
            return {"call_id": c.id, "with": who, "since": c.started}
    return None


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
                    "upi_id": f.upi_id,
                    "since": link.get("since", 0.0),
                }
            )
    return out


def _account(cust: Customer) -> dict:
    return {
        "id": cust.id,
        "name": cust.name,
        "mobile": cust.registered_mobile,
        "account_no": cust.account_no,
        "upi_id": cust.upi_id,
        "card_last4": cust.card_last4,
        "balance": cust.balance,
        "check_channel": cust.check_channel,
        "share_call_status": cust.share_call_status,
        "kill_switch": cust.kill_switch,
    }


# ------------------------------------------------------------------ sign-up
@router.post("/signup")
async def signup(body: Signup, request: Request) -> dict:
    if not _allow_signup(auth.client_key(request)):
        raise HTTPException(429, "Too many accounts from this phone. Use the one you have, or wait a few minutes.")
    if world.by_mobile(body.mobile):
        raise HTTPException(409, "That mobile number already has a CS Bank account. Use the phone you signed up with, or another number.")
    cust = _new_account(body.name, body.mobile)
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
    return {"token": auth.make_device_token(cust.id), "account": _account(cust)}


@router.post("/claim")
async def claim(body: Claim, request: Request) -> dict:
    """A team phone (or the IndiaCall simulator) takes a seeded account. Staff PIN only."""
    if not auth.is_staff(request):
        raise HTTPException(401, "staff PIN required")
    cust = world.customer(body.customer_id)
    if cust is None:
        raise HTTPException(404, "no such customer")
    devicekeys.register_device(cust.id, body.public_key, body.device)
    return {"token": auth.make_device_token(cust.id), "account": _account(cust)}


@router.get("/home")
async def home(request: Request) -> dict:
    cust = _me(request)
    pays = db.query("SELECT * FROM requests WHERE customer_id=? AND channel='app' ORDER BY created_at DESC LIMIT 15", [cust.id])
    return {
        "account": _account(cust),
        "family": _family(cust),
        "join_requests": [
            {"customer_id": j, "name": world.customer(j).name, "label": r["label"]} for j, r in _join_requests.get(cust.id, {}).items() if world.customer(j)
        ],
        "approvals": devicekeys.pending_for(cust.id),
        "payments": [guard.public(p) for p in pays],
        "bank_call": _bank_call(cust.id),
    }


@router.post("/prefs")
async def prefs(body: Prefs, request: Request) -> dict:
    cust = _me(request)
    if body.check_channel is not None:
        cust.check_channel = body.check_channel
    if body.share_call_status is not None:
        cust.share_call_status = body.share_call_status
    world.save(cust)
    db.audit(cust.id, "prefs_changed", cust.id, channel=cust.check_channel, share=cust.share_call_status)
    return _account(cust)


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


# ------------------------------------------------------------------ call state
@router.post("/call-state")
async def call_state(body: CallState, request: Request) -> dict:
    """The phone is on a call, or just finished one. Only the fact of the call: no number, no audio."""
    me = _me(request)
    if body.state == "active":
        prev = world.on_call.get(me.id)
        world.on_call[me.id] = {"kind": body.kind, "direction": body.direction, "since": prev["since"] if prev else time.time()}
    else:
        world.on_call.pop(me.id, None)
        world.recent_calls[me.id] = time.time()
    db.audit(me.id, f"phone_call_{body.state}", None, kind=body.kind, direction=body.direction)
    hub.publish("demo", {"type": "call_state", "customer": me.id, "state": body.state, "kind": body.kind})
    # anyone checking with me right now sees my call status change (only if I share it)
    if me.share_call_status:
        for p in db.query("SELECT * FROM requests WHERE channel='app' AND status IN ('awaiting_family','paused','held')"):
            if any(a["family_id"] == me.id for a in p["details"].get("asked") or []):
                hub.publish(f"app:{p['customer_id']}", {"type": "payment", "payment": guard.public(p), "message": ""})
    return {"ok": True}


# ------------------------------------------------------------------ payments
def _own_payment(pid: str, request: Request) -> Customer:
    me = _me(request)
    if guard.payment_customer(pid) != me.id:
        raise HTTPException(403, "not your payment")
    return me


@router.post("/pay")
async def pay(body: Pay, request: Request) -> dict:
    me = _me(request)
    return guard.start_payment(me.id, body.payee, body.amount, body.note)


@router.get("/payments/{pid}")
async def payment(pid: str, request: Request) -> dict:
    _own_payment(pid, request)
    return guard.public(db.get("requests", pid))


@router.post("/payments/{pid}/asked")
async def payment_asked(pid: str, body: Asked, request: Request) -> dict:
    _own_payment(pid, request)
    return guard.answer_asked(pid, body.someone_asked)


@router.post("/payments/{pid}/ask/{fid}")
async def payment_ask(pid: str, fid: str, request: Request) -> dict:
    _own_payment(pid, request)
    return guard.ask_family(pid, fid)


@router.post("/payments/{pid}/ask-all")
async def payment_ask_all(pid: str, request: Request) -> dict:
    _own_payment(pid, request)
    return guard.ask_all(pid)


@router.post("/payments/{pid}/redirect/{fid}")
async def payment_redirect(pid: str, fid: str, request: Request) -> dict:
    _own_payment(pid, request)
    return guard.redirect(pid, fid)


@router.post("/payments/{pid}/hold")
async def payment_hold(pid: str, request: Request) -> dict:
    _own_payment(pid, request)
    return guard.send_with_hold(pid)


@router.post("/payments/{pid}/cancel")
async def payment_cancel(pid: str, request: Request) -> dict:
    me = _own_payment(pid, request)
    return guard.cancel(pid, by=me.id)


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
    elif a["kind"] == "family_ping":
        guard.on_family_decision(a)
    elif a["kind"] == "kill_switch_off":
        if a["status"] == "approved" and me.kill_switch:
            me.kill_switch = {**me.kill_switch, "off_at": time.time() + KILL_SWITCH_WAIT_S}
            world.save(me)
            db.audit(me.id, "kill_switch_off_requested", me.id)
    else:
        from engine import approvals  # the contact-centre side: approve or decline a change asked for on a call

        approvals.on_decision(a)
    return a


# ------------------------------------------------------------------ kill switch
@router.post("/kill-switch")
async def kill_switch_on(request: Request) -> dict:
    """Block all payments and account changes now. Always allowed, no checks: it only protects."""
    me = guard.kill_switch_on(_me(request).id, by="customer")
    return _account(me)


@router.post("/kill-switch/off")
async def kill_switch_off(request: Request) -> dict:
    """Turning it off takes a fingerprint-signed approval, then an hour's wait."""
    me = _me(request)
    if not me.kill_switch:
        raise HTTPException(409, "The kill switch is already off.")
    return devicekeys.request_approval(
        f"ks_{me.id}",
        me.id,
        "kill_switch_off",
        {"question": "Turn the kill switch off?", "detail": "Payments and account changes will work again one hour after you confirm."},
    )


# ------------------------------------------------------------------ attack mode
@router.get("/leaked")
async def leaked(mobile: str, request: Request) -> dict:
    """Attack mode only: what a fraudster typically already has from a data leak (name and card
    digits) for the number they're about to impersonate. Demo accounts hold no real data. The point
    is that knowing these gets an attacker nowhere: the code and the approval go to the real phone."""
    _me(request)
    m = re.sub(r"[\s-]", "", mobile)
    cust = world.by_mobile(m if m.startswith("+") else "+91" + m[-10:])
    if cust is None:
        raise HTTPException(404, "No CS Bank account has that number.")
    return {"name": cust.name, "card_last4": cust.card_last4}


# ------------------------------------------------------------------ files: the APK and attack-mode clips
def samples() -> list[dict]:
    """Cloned-voice clips the app's attack mode can play: app/samples/*.wav, labelled by app/samples/labels.json."""
    d = settings.app_dir / "samples"
    if not d.is_dir():
        return []
    labels_file = d / "labels.json"
    labels = json.loads(labels_file.read_text(encoding="utf-8")) if labels_file.exists() else {}
    return [{"id": f.stem, "label": labels.get(f.name) or re.sub(r"[_-]+", " ", f.stem).strip().capitalize()} for f in sorted(d.glob("*.wav"))]


@router.get("/samples")
async def list_samples() -> list[dict]:
    return samples()


@router.get("/samples/{sid}")
async def get_sample(sid: str):
    if not re.fullmatch(r"[\w.-]+", sid) or not any(s["id"] == sid for s in samples()):
        raise HTTPException(404, "no such sample")
    return FileResponse(settings.app_dir / "samples" / f"{sid}.wav", media_type="audio/wav")


@files.get("/download/cs-bank.apk", include_in_schema=False)
async def download_apk():
    p = settings.app_dir / "cs-bank.apk"
    if not p.is_file():
        raise HTTPException(404, "The CS Bank app isn't on this server yet.")
    return FileResponse(p, media_type="application/vnd.android.package-archive", filename="cs-bank.apk")
