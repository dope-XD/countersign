"""Is this caller really my family member's phone? (docs/agents/CONTRACT.md, "Calls and checks")

Every family member runs the app, and each app reports its own calls: ringing, outgoing,
answered, ended, and which family member is on the other end (matched on the phone; raw
numbers never reach us). When someone rings Mom as "Rahul", we look at Rahul's own reports
around the moment Mom's phone rang:

    calling Mom                       -> verified (likely if they linked under 24 h ago)
    started a call then, peer unknown -> likely
    on a call, but not with Mom       -> not_with_you
    no call, app seen in the last 2m  -> not_them (spoof_suspected if Mom saw Rahul's number)
    app not seen for 2 minutes        -> cant_reach (never a false "not them")

A cloned voice, a friend's phone and a spoofed caller ID all fail the same way, because
none of them makes Rahul's phone place the call. No audio is involved.

A negative verdict waits up to WAIT_S for late events before it's final. A final ✗, or a
"No" to the ring, turns on scam context for the asker: the app then guards payment apps.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections import deque
from dataclasses import dataclass

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from engine import cases
from engine.db import db, new_id
from engine.hub import hub
from engine.mocks.world import DAY, Customer, world
from engine.stepup import devicekeys

router = APIRouter(prefix="/api/m")

EVENT_TTL = 1800.0  # call events are forgotten after 30 minutes
CHECK_TTL = DAY  # checks stay in the history for a day
WAIT_S = 6.0  # how long a negative verdict waits for the other phone's late events
ONLINE_S = 120.0  # app seen this recently = it would have reported a call
BEFORE_S, AFTER_S = 45.0, 5.0  # an outgoing call on their phone that started in [T-45 s, T+5 s] is "this call"
NEW_LINK_S = DAY
SCAM_AFTER_END_S = 600.0  # the pay guard stays on for 10 minutes after the scam call ends
MAX_EVENTS = 200

POSITIVE = ("verified", "likely")
NEGATIVE = ("not_with_you", "not_them")


@dataclass
class Event:
    call_id: str
    event: str
    kind: str
    peer: str | None
    at: float


_events: dict[str, deque[Event]] = {}  # customer -> their phone's call events, oldest first
_checks: dict[str, dict] = {}
_scam: dict[str, dict] = {}  # asker -> the check that made this call a scam
_last_event: dict[str, float] = {}
_alerts: dict[tuple[str, str], str] = {}  # (customer, call id) -> scam-alert id: the family is alarmed once per call
_cleared: set[tuple[str, str]] = set()  # (customer, call id) the user said was not a scam
false_alarms: deque[dict] = deque(maxlen=1000)  # ids-only feedback records for human review (counted in /api/metrics)


# ------------------------------------------------------------------ bodies
class CallEvent(BaseModel):
    call_id: str = Field(min_length=1, max_length=64)
    event: str = Field(pattern="^(ringing|outgoing|answered|ended)$")
    kind: str = Field(default="phone", pattern="^(phone|internet)$")
    peer: str | None = Field(default=None, max_length=64)
    elapsed_ms: int = Field(default=0, ge=0, le=600_000)

    @field_validator("peer")
    @classmethod
    def _no_numbers(cls, v: str | None) -> str | None:
        if v is not None and (re.fullmatch(r"[+\d\s()-]{6,}", v) or not re.fullmatch(r"[A-Za-z0-9_]+", v)):
            raise ValueError("peer must be a family member's id; phone numbers never leave the phone")
        return v


SCAM_TYPES = (
    "digital_arrest", "bank_kyc", "otp_upi", "remote_access", "family_emergency", "courier_customs",
    "trai_sim", "job_task", "investment", "reward", "impersonation", "unknown",
)  # fmt: skip
SOURCES = ("cues", "phone_ai", "voice", "context", "caller_check", "user")


class ScamAlert(BaseModel):
    """The phone's call listener decided this call is a scam. Ids only: no words, no audio."""

    call_id: str = Field(min_length=1, max_length=64)
    level: str = Field(pattern="^scam$")
    type: str = "unknown"
    cues: list[str] = Field(default_factory=list, max_length=30)
    sources: list[str] = Field(default_factory=list, max_length=6)

    @field_validator("type")
    @classmethod
    def _type(cls, v: str) -> str:
        if v not in SCAM_TYPES:
            raise ValueError("unknown scam type")
        return v

    @field_validator("cues")
    @classmethod
    def _cues(cls, v: list[str]) -> list[str]:
        if any(not re.fullmatch(r"[a-z_]{1,40}", c) for c in v):
            raise ValueError("cues are category ids, never words from the call")
        return v

    @field_validator("sources")
    @classmethod
    def _sources(cls, v: list[str]) -> list[str]:
        if any(s not in SOURCES for s in v):
            raise ValueError("unknown source")
        return v


class NotAScam(ScamAlert):
    """The user pressed "Not a scam" or "I know this caller" on a warn or scam card. Ids only."""

    reason: str = Field(pattern="^(know_caller|not_a_scam)$")
    level: str = Field(default="warn", pattern="^(watch|warn|scam)$")


class NewCheck(BaseModel):
    call_id: str = Field(min_length=1, max_length=64)
    claimed: str = Field(min_length=1, max_length=64)
    number_matched: bool = False
    via: str = Field(default="manual", pattern="^(auto|manual)$")


# ------------------------------------------------------------------ the phones' calls
def record(customer_id: str, ev: CallEvent) -> None:
    now = time.time()
    q = _events.setdefault(customer_id, deque(maxlen=MAX_EVENTS))
    q.append(Event(ev.call_id, ev.event, ev.kind, ev.peer, now - ev.elapsed_ms / 1000))
    _last_event[customer_id] = now
    # keep the older call-state view (signals, demo panel) in step
    if ev.event == "ended":
        world.on_call.pop(customer_id, None)
        world.recent_calls[customer_id] = now
    else:
        direction = "outgoing" if ev.event == "outgoing" else "incoming"
        prev = world.on_call.get(customer_id)
        world.on_call[customer_id] = {"kind": ev.kind, "direction": prev["direction"] if prev else direction, "since": prev["since"] if prev else now}


def _calls(customer_id: str) -> dict[str, dict]:
    """call_id -> {start, end, outgoing, peer, kind}, from that phone's events."""
    out: dict[str, dict] = {}
    for e in _events.get(customer_id, ()):
        c = out.setdefault(e.call_id, {"start": e.at, "end": None, "outgoing": False, "peer": None, "kind": e.kind})
        if e.event == "outgoing":
            c["outgoing"] = True
        if e.event in ("ringing", "outgoing"):
            c["start"] = min(c["start"], e.at)
        if e.event == "ended":
            c["end"] = e.at
        c["peer"] = e.peer or c["peer"]
    return out


def _ring_time(check: dict) -> float:
    """T: when the asker's phone started this call, else when they asked."""
    c = _calls(check["asker"]).get(check["call_id"])
    return c["start"] if c else check["created_at"]


def seen(customer_id: str) -> float:
    return max(world.app_sessions.get(customer_id, 0.0), _last_event.get(customer_id, 0.0))


def evaluate(check: dict) -> str:
    asker, claimed = check["asker"], check["member"]
    t = _ring_time(check)
    # a call of theirs that had already ended when Mom's phone rang can't be this call
    theirs = [c for c in _calls(claimed).values() if c["end"] is None or c["end"] >= t]
    with_me = [c for c in theirs if c["peer"] == asker and t - BEFORE_S <= c["start"] <= t + AFTER_S]
    if with_me:
        old = time.time() - (world.customer(asker).family.get(claimed) or {}).get("since", 0.0) >= NEW_LINK_S
        return "verified" if old else "likely"
    if any(c["outgoing"] and c["peer"] is None and t - BEFORE_S <= c["start"] <= t + AFTER_S for c in theirs):
        return "likely"
    if any(c["start"] <= t + AFTER_S for c in theirs):
        return "not_with_you"
    if time.time() - seen(claimed) <= ONLINE_S:
        return "not_them"
    return "cant_reach"


# ------------------------------------------------------------------ checks
def public(c: dict) -> dict:
    return {
        "id": c["id"],
        "call_id": c["call_id"],
        "member": c["member"],
        "label": c["label"],
        "verdict": c["verdict"],
        "number_matched": c["number_matched"],
        "spoof_suspected": c["verdict"] == "not_them" and c["number_matched"],
        "ring": c["ring"],
        "created_at": c["created_at"],
        "decided_at": c["decided_at"],
    }


def _push(c: dict) -> None:
    hub.publish(f"app:{c['asker']}", {"type": "call_check", "check": public(c)})


def settle(cid: str) -> dict:
    """Bring a check up to date: early ✓ on a late event, the final verdict at its deadline, an unanswered ring."""
    c = _checks[cid]
    changed = False
    if c["decided_at"] is None:
        v = evaluate(c)
        if v in POSITIVE or time.time() >= c["deadline"]:
            c["verdict"], c["decided_at"] = v, time.time()
            changed = True
            _on_final(c)
    if c["ring"] == "ringing" and c.get("approval") and not devicekeys.is_open(c["approval"]):
        a = db.get("approvals", c["approval"])
        if a and a["status"] == "pending":
            devicekeys.expire(c["approval"])
            c["ring"] = "no_answer"
            changed = True
    if changed:
        _push(c)
    return c


def _on_final(c: dict) -> None:
    db.audit(c["asker"], "call_check", c["id"], member=c["member"], verdict=c["verdict"], via=c["via"])
    if c["verdict"] not in NEGATIVE:
        return
    _set_scam(c, c["verdict"])
    if c["verdict"] == "not_them" and c["number_matched"]:
        # someone is showing the member's number to their family: tell the member
        me, asker = world.customer(c["member"]), world.customer(c["asker"])
        if me and asker:
            hub.publish(f"app:{me.id}", {"type": "spoof_alert", "by": asker.first_name, "label": me.label_for(asker.id), "at": time.time()})


def _set_scam(c: dict, reason: str) -> None:
    case = _mark_scam(
        c["asker"],
        c["id"],
        c["member"],
        c["label"],
        reason,
        c["call_id"],
        ["IMPERSONATION_CALL", reason.upper()],
        {"spoof_suspected": c["verdict"] == "not_them" and c["number_matched"]},
        event=f"call_check_{reason}",
    )
    c["case_id"] = case["id"]


def _mark_scam(asker: str, ref: str, member: str, label: str, reason: str, call_id: str, case_reasons: list[str], scores: dict, event: str) -> dict:
    """Turn on scam context for this phone (the pay guard), open or extend the fraud-desk case, tell the phone."""
    _scam[asker] = {"check_id": ref, "member": member, "label": label, "reason": reason, "call_id": call_id}
    case = cases.open_case(channel="app", customer_id=asker, request_id=ref, tier="RED", reasons=case_reasons, scores=scores, event=event)
    hub.publish(f"app:{asker}", {"type": "scam", "scam": scam_for(asker)})
    return case


def scam_for(customer_id: str) -> dict | None:
    """The scam context for this phone, while it lasts (the call, then 10 minutes)."""
    s = _scam.get(customer_id)
    if s is None:
        return None
    call = _calls(customer_id).get(s["call_id"])
    until = (call["end"] if call and call["end"] else time.time()) + SCAM_AFTER_END_S
    if until < time.time():
        del _scam[customer_id]
        return None
    return {k: s[k] for k in ("check_id", "member", "label", "reason")} | {"until": until}


def recent(customer_id: str, n: int = 10) -> list[dict]:
    mine = sorted((c for c in _checks.values() if c["asker"] == customer_id), key=lambda c: c["created_at"], reverse=True)
    return [public(settle(c["id"])) for c in mine[:n]]


def _family_member(me: Customer, member: str) -> Customer:
    m = world.customer(member)
    if member not in me.family or m is None:
        raise HTTPException(404, "That person isn't in your family.")
    return m


def _mine(cid: str, me: Customer) -> dict:
    c = _checks.get(cid)
    if c is None or c["asker"] != me.id:
        raise HTTPException(404, "That check has ended.")
    return settle(cid)


def on_ring_decision(approval: dict) -> None:
    """The member answered "Is it you on Mom's call?" (mobile.decide)."""
    c = _checks.get(approval["request_id"])
    if c is None or c["ring"] != "ringing":
        return
    if approval["status"] == "approved":
        c["ring"] = "yes"
        s = _scam.get(c["asker"])
        if s and s["check_id"] == c["id"]:
            del _scam[c["asker"]]
            hub.publish(f"app:{c['asker']}", {"type": "scam", "scam": None})
    elif approval["status"] == "declined":
        c["ring"] = "no"
        _set_scam(c, "ring_no")
    _push(c)


def prune() -> None:
    now = time.time()
    for q in _events.values():
        while q and q[0].at < now - EVENT_TTL:
            q.popleft()
    for cid in [k for k, c in _checks.items() if c["created_at"] < now - CHECK_TTL]:
        del _checks[cid]
    for who in list(_scam):
        scam_for(who)


def reset() -> None:
    _events.clear()
    _checks.clear()
    _scam.clear()
    _last_event.clear()
    _alerts.clear()


# ------------------------------------------------------------------ routes
def _me(request: Request) -> Customer:
    from engine import mobile

    return mobile._me(request)


@router.post("/call-event")
async def call_event(body: CallEvent, request: Request) -> dict:
    me = _me(request)
    if body.peer is not None and body.peer not in me.family:
        raise HTTPException(422, "peer must be one of your family members' ids")
    record(me.id, body)
    # a late event from my phone may settle someone's pending check about me at once
    for c in list(_checks.values()):
        if c["member"] == me.id and c["decided_at"] is None:
            settle(c["id"])
    return {"ok": True}


@router.post("/checks")
async def new_check(body: NewCheck, request: Request) -> dict:
    me = _me(request)
    m = _family_member(me, body.claimed)
    now = time.time()
    c = {
        "id": new_id("chk"),
        "asker": me.id,
        "call_id": body.call_id,
        "member": m.id,
        "label": me.label_for(m.id),
        "verdict": "checking",
        "number_matched": body.number_matched,
        "via": body.via,
        "ring": "none",
        "approval": None,
        "created_at": now,
        "decided_at": None,
        "deadline": now + WAIT_S,
    }
    _checks[c["id"]] = c
    settle(c["id"])
    if c["decided_at"] is None:
        asyncio.get_running_loop().call_later(max(0.0, c["deadline"] - time.time()) + 0.05, settle, c["id"])
    return public(c)


@router.get("/checks")
async def list_checks(request: Request) -> list[dict]:
    return recent(_me(request).id)


@router.get("/checks/{cid}")
async def get_check(cid: str, request: Request) -> dict:
    return public(_mine(cid, _me(request)))


@router.post("/checks/{cid}/ring")
async def ring(cid: str, request: Request) -> dict:
    me = _me(request)
    c = _mine(cid, me)
    if c["ring"] == "ringing":
        return public(c)
    m = _family_member(me, c["member"])
    what_they_call_me = m.label_for(me.id)
    a = devicekeys.request_approval(
        c["id"],
        m.id,
        "call_check",
        {
            "from": what_they_call_me,
            "question": f"Is it you on {what_they_call_me}'s call?",
            "detail": f"Someone on a call to {what_they_call_me} says they're you.",
        },
    )
    c["ring"], c["approval"] = "ringing", a["id"]
    db.audit(me.id, "call_check_ring", c["id"], member=m.id)
    _push(c)
    return public(c)


@router.post("/scam/dismiss")
async def dismiss_scam(request: Request) -> dict:
    me = _me(request)
    s = _scam.pop(me.id, None)
    if s:
        db.audit(me.id, "scam_warning_dismissed", s["check_id"])
        hub.publish(f"app:{me.id}", {"type": "scam", "scam": None})
    return {"scam": None}


@router.post("/scam-alert")
async def scam_alert(body: ScamAlert, request: Request) -> dict:
    """The listener's verdict reached "scam" (or the user pressed "Alert family"): pay guard on, a fraud-desk case,
    and every family member's phone rings. Members whose app is offline come back in `text_these`, so the phone can
    text them from its own SIM."""
    me = _me(request)
    key = (me.id, body.call_id)
    if key in _cleared:  # the user already said this call is fine
        return {"scam": scam_for(me.id), "alarmed": [], "text_these": []}
    first = key not in _alerts
    aid = _alerts.setdefault(key, new_id("lsn"))
    if me.id not in _scam:  # a caller-check scam on this call already has the pay guard on: keep its reason
        _mark_scam(
            me.id,
            aid,
            "",
            "",
            f"listener:{body.type}",
            body.call_id,
            ["SCAM_CALL", body.type.upper()],
            {"cues": body.cues, "sources": body.sources},
            event="listener_scam",
        )
    alarmed, text_these = [], []
    if first:
        db.audit(me.id, "scam_call_alert", aid, type=body.type, cues=body.cues, sources=body.sources)
        now = time.time()
        for fid in me.family:
            member = world.customer(fid)
            if member is None:
                continue
            hub.publish(
                f"app:{fid}",
                {"type": "family_alarm", "from": me.id, "label": member.label_for(me.id), "scam_type": body.type, "level": "scam", "at": now},
            )
            (alarmed if now - seen(fid) <= ONLINE_S else text_these).append(fid)
        db.audit(me.id, "family_alarmed", aid, online=alarmed, offline=text_these)
    return {"scam": scam_for(me.id), "alarmed": alarmed, "text_these": text_these}


@router.post("/scam-alert/clear")
async def scam_alert_clear(body: NotAScam, request: Request) -> dict:
    """A false alarm: the pay guard goes off, family who were alarmed for this call get family_alarm_cleared, and one
    ids-only feedback record is kept for human review. Later alerts for the same call don't alarm anyone."""
    me = _me(request)
    key = (me.id, body.call_id)
    _cleared.add(key)
    aid = _alerts.get(key)
    s = _scam.get(me.id)
    if s and (s.get("call_id") == body.call_id or s["check_id"] == aid):
        _scam.pop(me.id, None)
        hub.publish(f"app:{me.id}", {"type": "scam", "scam": None})
    told = []
    if aid:
        now = time.time()
        for fid in me.family:
            member = world.customer(fid)
            if member is None:
                continue
            hub.publish(f"app:{fid}", {"type": "family_alarm_cleared", "from": me.id, "label": member.label_for(me.id), "reason": body.reason, "at": now})
            told.append(fid)
    record = {
        "at": time.time(),
        "call_id": body.call_id,
        "reason": body.reason,
        "level": body.level,
        "type": body.type,
        "cues": body.cues,
        "sources": body.sources,
    }
    false_alarms.append(record)
    db.audit(me.id, "false_alarm", aid or body.call_id, **{k: v for k, v in record.items() if k not in ("at", "call_id")})
    return {"scam": scam_for(me.id), "cleared": told}
