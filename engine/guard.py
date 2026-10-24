"""The 'paying under pressure' guard in the CS Bank app, and the family check.

The app cannot hear calls (Android blocks it), so the guard uses what it can know: the phone
is on a call (or was, a few minutes ago), the payee is new, the amount is large, the payee is
flagged on DoT's FRI. When those line up, the payment pauses and the payer can ask a family
member's phone "did you ask for this?". This is the RBI's April 2026 "trusted person" idea,
triggered by risk instead of by age.

It pauses, never blocks. Every way forward is harmless if the story is true and useless to a
scammer:
- ask one family member, or all of them (one "No" stops it);
- send the money to the family member's own account instead;
- send it with a one-hour hold (the RBI's "golden hour"), cancellable by the payer or by a
  family member's late "No".
"""

from __future__ import annotations

import time

from engine import cases
from engine.db import db, new_id
from engine.hub import hub
from engine.mocks.world import DAY, Customer, world
from engine.stepup import devicekeys

CALL_WINDOW = 600  # a call active or ended in the last 10 minutes
ASK_MIN = 10_000  # first payment this big to a new payee asks "did someone ask you for this?"
HOLD_MIN = 10_000  # payments this big wait out the golden hour when sent despite a pause
HOLD_S = 3600.0
ANSWER_WAIT_S = 60.0  # then the payer sees "no answer" and the other options
YOUNG_LINK_S = DAY  # a family link this new can stop a payment but not release it at once
ON_HOLD = ("confirm", "paused", "awaiting_family")


class GuardError(Exception):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def inr(x: float) -> str:
    s = f"{int(round(x)):d}"
    if len(s) <= 3:
        return "₹" + s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return "₹" + ",".join(parts) + "," + tail


def _payment(payment_id: str) -> dict:
    p = db.get("requests", payment_id)
    if p is None or p["channel"] != "app":
        raise GuardError("no such payment", 404)
    return p


def payment_customer(payment_id: str) -> str:
    """Whose payment this is (for the app's auth check)."""
    return _payment(payment_id)["customer_id"]


def _whitelisted(cust: Customer, payee: str) -> bool:
    """Known payees and family members' own accounts never pause (RBI: whitelisted beneficiaries)."""
    if payee in cust.known_payees:
        return True
    to = world.by_upi(payee)
    return bool(to and to.id in cust.family)


def evaluate(customer_id: str, payee: str, amount: float) -> dict:
    cust = world.customer(customer_id)
    call_t = world.recent_calls.get(customer_id)
    on_call = world.on_call.get(customer_id)
    call_seen = bool(on_call) or bool(call_t and time.time() - call_t < CALL_WINDOW)
    whitelisted = _whitelisted(cust, payee)
    big = amount > cust.usual_upi_max
    fri = world.fri_rating(payee)
    reasons, tips = [], []
    if on_call:
        reasons.append("You're on a call right now" if on_call["kind"] == "phone" else "You're on an internet call (like WhatsApp) right now")
    elif call_seen:
        mins = max(1, int((time.time() - call_t) // 60))
        reasons.append(f"You were on a call {mins} minute{'s' if mins != 1 else ''} ago")
    if not whitelisted:
        reasons.append("this is a new payee")
    if big:
        reasons.append(f"{inr(amount)} is more than you usually send")
    if fri:
        reasons.append(f"this payee's number is flagged {fri} risk by the telecom department")
    if on_call and on_call["kind"] == "internet":
        tips.append("Police and government agencies never ask for money on a video or WhatsApp call.")
    fires = not whitelisted and (call_seen and (big or bool(fri)) or fri in ("High", "Very High"))
    confirm = not fires and not whitelisted and amount >= ASK_MIN
    return {
        "fires": fires,
        "confirm": confirm,
        "call_seen": call_seen,
        "call_kind": on_call["kind"] if on_call else ("phone" if call_seen else None),
        "new_payee": not whitelisted,
        "big": big,
        "fri": fri,
        "reasons": reasons,
        "tips": tips,
    }


# ---------------------------------------------------------------- money movement
def _move(payer: Customer, payee: str, amount: float) -> None:
    payer.balance -= amount
    world.save(payer)
    to = world.by_upi(payee)
    if to is not None and to.id != payer.id:
        to.balance += amount
        world.save(to)


def _refund(payer: Customer, amount: float) -> None:
    payer.balance += amount
    world.save(payer)


def _set(pid: str, status: str, **details) -> dict:
    p = _payment(pid)
    d = {**p["details"], **details}
    db.update("requests", pid, {"status": status, "details": d, "updated_at": time.time()})
    return _payment(pid)


def _publish(p: dict, message: str = "", tone: str = "info") -> None:
    hub.publish(f"app:{p['customer_id']}", {"type": "payment", "payment": public(p), "message": message, "tone": tone})


# ---------------------------------------------------------------- what the payer's phone shows
def family_status(member_id: str) -> dict:
    """What a family member's phone says right now, if they share it. Only shown while a check is open."""
    fam = world.customer(member_id)
    if fam is None or not fam.share_call_status:
        return {"shared": False}
    oc = world.on_call.get(member_id)
    seen = world.app_sessions.get(member_id)
    return {
        "shared": True,
        "on_call": bool(oc),
        "call_kind": oc["kind"] if oc else None,
        "app_seen_s_ago": round(time.time() - seen) if seen else None,
    }


def _family_option(payer: Customer, fid: str, show_status: bool) -> dict | None:
    fam = world.customer(fid)
    if fam is None:
        return None
    since = (fam.family.get(payer.id) or {}).get("since", 0.0)
    out = {
        "id": fid,
        "label": payer.label_for(fid),
        "name": fam.name,
        "mobile": fam.registered_mobile,
        "upi_id": fam.upi_id,
        "new_link": time.time() - since < YOUNG_LINK_S,
        "sim_swapped_recently": world.sim_swapped_within(fam.registered_mobile, 3 * DAY),
    }
    if show_status:
        out["status"] = family_status(fid)
    return out


def public(p: dict) -> dict:
    d = p["details"]
    payer = world.customer(p["customer_id"])
    asked = d.get("asked") or []
    checking = p["status"] in ("awaiting_family", "paused", "held")
    answers = {}
    for a in asked:
        with_status = devicekeys.public_approval(a["approval_id"]) if db.get("approvals", a["approval_id"]) else None
        answers[a["family_id"]] = with_status["status"] if with_status else "unknown"
    asked_ids = {a["family_id"] for a in asked}
    family = [_family_option(payer, f, checking and f in asked_ids) for f in payer.family] if payer else []
    for f in family:
        if f and f["id"] in answers:
            f["answer"] = answers[f["id"]]
    return {
        "id": p["id"],
        "payee": d["payee"],
        "amount": d["amount"],
        "amount_text": inr(d["amount"]),
        "note": d.get("note", ""),
        "status": p["status"],
        "guard": d.get("guard"),
        "hold_until": d.get("hold_until"),
        "redirected_to": d.get("redirected_to"),
        "no_answer": d.get("no_answer", False),
        "case_id": d.get("case_id"),
        "report": d.get("report"),
        "family": [f for f in family if f],
        "created_at": p["created_at"],
    }


# ---------------------------------------------------------------- the flow
def start_payment(customer_id: str, payee: str, amount: float, note: str = "") -> dict:
    cust = world.customer(customer_id)
    if cust is None:
        raise GuardError("no such customer", 404)
    if cust.blocked():
        raise GuardError("Your kill switch is on, so payments are blocked. Turn it off in the app first.", 423)
    if payee == cust.upi_id:
        raise GuardError("That's your own account.", 400)
    if amount > cust.balance:
        raise GuardError("Not enough balance for this payment.", 400)
    g = evaluate(customer_id, payee, amount)
    pid = new_id("pay")
    now = time.time()
    status = "paused" if g["fires"] else "confirm" if g["confirm"] else "executed"
    db.insert(
        "requests",
        {
            "id": pid,
            "customer_id": customer_id,
            "channel": "app",
            "call_id": None,
            "action": "upi_payment",
            "details": {"payee": payee, "amount": amount, "note": note, "guard": g, "asked": []},
            "tier": None,
            "policy": {"guard": g["fires"], "reqs": {}},
            "status": status,
            "created_at": now,
            "updated_at": now,
            "cooloff_until": None,
        },
    )
    db.audit(customer_id, {"paused": "guard_fired", "confirm": "guard_asked", "executed": "payment_sent"}[status], pid, amount=amount)
    if status == "executed":
        _move(cust, payee, amount)
    return public(_payment(pid))


def answer_asked(payment_id: str, someone_asked: bool) -> dict:
    """The payer's answer to "Did someone ask you for this money, by call or message?" (no call was seen)."""
    p = _payment(payment_id)
    if p["status"] != "confirm":
        raise GuardError(f"payment is already {p['status']}")
    if someone_asked:
        g = {**p["details"]["guard"], "fires": True, "asked_by_message": True}
        g["reasons"] = ["Someone asked you for this money", *g["reasons"]]
        p = _set(payment_id, "paused", guard=g)
        db.audit(p["customer_id"], "guard_fired", payment_id, trigger="someone_asked")
    else:
        _move(world.customer(p["customer_id"]), p["details"]["payee"], p["details"]["amount"])
        p = _set(payment_id, "executed")
        db.audit(p["customer_id"], "payment_sent", payment_id)
    return public(p)


def _check_summary(payer: Customer, fam: Customer, p: dict) -> dict:
    d = p["details"]
    g = d.get("guard") or {}
    me = fam.label_for(payer.id)  # what the family member calls the payer: "Mom"
    how = {"phone": "while on a phone call", "internet": "while on a WhatsApp or internet call"}.get(g.get("call_kind") or "", "")
    if g.get("asked_by_message"):
        how = "after someone asked for it by message"
    return {
        "question": f"Did you ask {me} for {inr(d['amount'])}?",
        "detail": f"{me} is about to send {inr(d['amount'])} to {d['payee']}{', ' + how if how else ''}. If you didn't ask, press No.",
        "amount": d["amount"],
        "payee": d["payee"],
        "from_customer": payer.id,
        "from_label": me,
    }


def ask_family(payment_id: str, family_id: str) -> dict:
    p = _payment(payment_id)
    if p["status"] not in ON_HOLD + ("held",):
        raise GuardError(f"payment is already {p['status']}")
    payer = world.customer(p["customer_id"])
    fam = world.customer(family_id)
    if fam is None or family_id not in payer.family:
        raise GuardError("not in your family", 403)
    asked = list(p["details"].get("asked") or [])
    open_ask = next((a for a in asked if a["family_id"] == family_id and devicekeys.is_open(a["approval_id"])), None)
    if open_ask is None:
        a = devicekeys.request_approval(payment_id, family_id, "family_ping", _check_summary(payer, fam, p))
        asked.append({"family_id": family_id, "approval_id": a["id"], "at": time.time()})
        db.audit(payer.id, "family_check_sent", payment_id, to=family_id)
    status = "held" if p["status"] == "held" else "awaiting_family"
    return public(_set(payment_id, status, asked=asked, no_answer=False))


def ask_all(payment_id: str) -> dict:
    p = _payment(payment_id)
    payer = world.customer(p["customer_id"])
    if not payer.family:
        raise GuardError("You haven't added any family yet.", 400)
    out = None
    for fid in payer.family:
        out = ask_family(payment_id, fid)
    return out


def _young(payer_id: str, family_id: str) -> bool:
    fam = world.customer(family_id)
    since = (fam.family.get(payer_id) or {}).get("since", 0.0) if fam else 0.0
    return time.time() - since < YOUNG_LINK_S


def on_family_decision(approval: dict) -> None:
    if approval["kind"] != "family_ping":
        return
    pid = approval["request_id"]
    p = db.get("requests", pid)
    if p is None or p["status"] not in ON_HOLD + ("held",):
        return
    payer = world.customer(p["customer_id"])
    fid = approval["target_customer"]
    who = payer.label_for(fid)
    d = p["details"]
    if approval["status"] == "declined":
        if p["status"] == "held":
            _refund(payer, d["amount"])
        case = cases.open_case(
            channel="app",
            customer_id=payer.id,
            request_id=pid,
            tier="RED",
            reasons=["FAMILY_DECLINED"],
            scores={"amount": d["amount"]},
            event="family_declined",
        )
        report = prefill_1930(pid, case["id"])
        p = _set(pid, "cancelled", case_id=case["id"], report=report)
        db.audit("family", "payment_cancelled_by_family", pid, by=fid)
        _publish(p, f"{who} says they did not ask for this. We stopped the payment. Hang up, and don't send money to anyone on this call.", "danger")
    elif approval["status"] == "approved":
        if _young(payer.id, fid):
            # a family link made today can't release money at once: it goes out with the golden-hour hold
            if p["status"] != "held":
                p = _hold(p)
            _publish(p, f"{who} confirmed. You joined each other's family today, so the money leaves after a one-hour hold you can still cancel.", "warn")
        else:
            if p["status"] == "held":
                _release(p)
            else:
                _move(payer, d["payee"], d["amount"])
            p = _set(pid, "executed")
            db.audit("family", "payment_released_by_family", pid, by=fid)
            _publish(p, f"{who} confirmed. Payment sent.", "ok")


def redirect(payment_id: str, family_id: str) -> dict:
    """Send the money to the family member's own account instead. If the story is true, they
    can use it; a scammer's account gets nothing."""
    p = _payment(payment_id)
    if p["status"] not in ON_HOLD:
        raise GuardError(f"payment is already {p['status']}")
    payer = world.customer(p["customer_id"])
    fam = world.customer(family_id)
    if fam is None or family_id not in payer.family:
        raise GuardError("not in your family", 403)
    d = p["details"]
    _move(payer, fam.upi_id, d["amount"])
    p = _set(payment_id, "executed", redirected_to={"id": fam.id, "label": payer.label_for(fam.id), "upi_id": fam.upi_id, "instead_of": d["payee"]})
    db.audit(payer.id, "payment_redirected_to_family", payment_id, to=family_id, instead_of=d["payee"])
    hub.publish(
        f"app:{family_id}",
        {
            "type": "alert",
            "title": f"{fam.label_for(payer.id)} sent you {inr(d['amount'])}",
            "body": "They were asked for money for you on a call. Call them back on their own number.",
        },
    )
    return public(p)


def _hold(p: dict) -> dict:
    payer = world.customer(p["customer_id"])
    payer.balance -= p["details"]["amount"]  # provisional debit, refunded if cancelled
    world.save(payer)
    db.audit(payer.id, "payment_held", p["id"])
    return _set(p["id"], "held", hold_until=time.time() + HOLD_S)


def _release(p: dict) -> None:
    to = world.by_upi(p["details"]["payee"])
    if to is not None and to.id != p["customer_id"]:
        to.balance += p["details"]["amount"]
        world.save(to)


def send_with_hold(payment_id: str) -> dict:
    """ "Send anyway": small amounts go now; large ones wait out the golden hour."""
    p = _payment(payment_id)
    if p["status"] not in ON_HOLD:
        raise GuardError(f"payment is already {p['status']}")
    if p["details"]["amount"] < HOLD_MIN:
        _move(world.customer(p["customer_id"]), p["details"]["payee"], p["details"]["amount"])
        db.audit(p["customer_id"], "payment_continued_after_pause", payment_id)
        return public(_set(payment_id, "executed"))
    return public(_hold(p))


def cancel(payment_id: str, by: str = "customer") -> dict:
    p = _payment(payment_id)
    if p["status"] == "held":
        _refund(world.customer(p["customer_id"]), p["details"]["amount"])
    elif p["status"] not in ON_HOLD:
        raise GuardError(f"payment is already {p['status']}")
    for a in p["details"].get("asked") or []:
        devicekeys.expire(a["approval_id"])
    db.audit(by, "payment_cancelled", payment_id)
    return public(_set(payment_id, "cancelled"))


def kill_switch_on(customer_id: str, by: str) -> Customer:
    """Block all payments and account changes now (RBI's proposed customer "kill switch"). Always
    allowed with no checks, from the app or on a call: it can only protect. Open payments are
    cancelled, held ones refunded, and open account-change requests cancelled."""
    from engine import policy

    cust = world.customer(customer_id)
    cust.kill_switch = {"since": time.time(), "off_at": None}
    world.save(cust)
    db.audit(by, "kill_switch_on", customer_id)
    for p in db.query(
        "SELECT id FROM requests WHERE customer_id=? AND channel='app' AND status IN ('confirm','paused','awaiting_family','held')", [customer_id]
    ):
        cancel(p["id"], by=by)
    for r in db.query("SELECT id FROM requests WHERE customer_id=? AND channel!='app' AND status='open'", [customer_id]):
        policy.cancel(r["id"], by, "customer turned on the kill switch")
    hub.publish(f"app:{customer_id}", {"type": "alert", "title": "Kill switch is ON", "body": "All payments and account changes are blocked."})
    return cust


def tick() -> None:
    """Called every few seconds: release holds whose hour is up, tell payers when a family check
    went unanswered, and lift kill switches whose wait is over."""
    now = time.time()
    for p in db.query("SELECT * FROM requests WHERE channel='app' AND status IN ('held','awaiting_family')"):
        d = p["details"]
        if p["status"] == "held" and d.get("hold_until") and now >= d["hold_until"]:
            _release(p)
            p = _set(p["id"], "executed")
            db.audit("system", "payment_released_after_hold", p["id"])
            _publish(p, "The hold is over. Payment sent.", "ok")
        elif p["status"] == "awaiting_family":
            asked = d.get("asked") or []
            if (
                asked
                and all(now - a["at"] > ANSWER_WAIT_S for a in asked)
                and not any((db.get("approvals", a["approval_id"]) or {}).get("status") in ("approved", "declined") for a in asked)
            ):
                p = _set(p["id"], "paused", no_answer=True)
                names = ", ".join(world.customer(p["customer_id"]).label_for(a["family_id"]) for a in asked)
                _publish(p, f"{names} hasn't answered yet. You can still wait, or use one of the safe options.", "warn")
    for c in world.customers.values():
        ks = c.kill_switch
        if ks and ks.get("off_at") and now >= ks["off_at"]:
            c.kill_switch = None
            world.save(c)
            db.audit(c.id, "kill_switch_off", c.id)
            hub.publish(f"app:{c.id}", {"type": "alert", "title": "Kill switch is off", "body": "Payments and account changes work again."})


def prefill_1930(payment_id: str, case_id: str | None = None) -> dict:
    p = _payment(payment_id)
    cust = world.customer(p["customer_id"])
    d = p["details"]
    payload = {
        "helpline": "1930",
        "portal": "cybercrime.gov.in",
        "complainant": cust.name,
        "mobile": cust.registered_mobile,
        "category": "Online financial fraud > Impersonation of a family member (possible AI voice)",
        "amount_attempted": d["amount"],
        "payee_vpa": d["payee"],
        "description": "Someone on a call asked for urgent money as a family member. The family member confirmed in the CS Bank app that they did not ask.",
        "status": "prefilled, not submitted",
    }
    rid = new_id("ncrp")
    db.insert("reports", {"id": rid, "kind": "ncrp_1930_prefill", "case_id": case_id, "created_at": time.time(), "payload": payload})
    return {"id": rid, **payload}
