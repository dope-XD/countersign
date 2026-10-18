"""Entry B: the 'paying under pressure' guard in the bank app, plus Family Circle.

The app cannot hear calls (Android/iOS block it), so the guard uses call state, payee and
amount. It pauses, never blocks: the customer can always continue.
"""
from __future__ import annotations

import time

from engine import cases
from engine.db import db, new_id
from engine.hub import hub
from engine.mocks.world import world
from engine.stepup import passkeys

CALL_WINDOW = 600  # a call active or ended in the last 10 minutes


def _inr(x: float) -> str:
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


def evaluate(customer_id: str, payee: str, amount: float) -> dict:
    cust = world.customer(customer_id)
    call_t = world.recent_calls.get(customer_id)
    call_seen = bool(call_t and time.time() - call_t < CALL_WINDOW)
    new_payee = payee not in cust.known_payees
    big = amount > cust.usual_upi_max
    fri = world.fri_rating(payee)
    reasons = []
    if call_seen:
        mins = max(1, int((time.time() - call_t) // 60))
        reasons.append(f"You were on a call {mins} minute{'s' if mins != 1 else ''} ago")
    if new_payee:
        reasons.append("this is a new payee")
    if big:
        reasons.append(f"{_inr(amount)} is more than you usually send")
    if fri:
        reasons.append(f"this payee's number is flagged {fri} risk by the telecom department")
    fires = False
    if call_seen and new_payee and (big or fri):
        fires = True
    elif cust.opted_in_guard and new_payee and big:
        fires = True
    elif fri in ("High", "Very High"):
        fires = True
    return {"fires": fires, "call_seen": call_seen, "new_payee": new_payee, "big": big, "fri": fri, "reasons": reasons}


def start_payment(customer_id: str, payee: str, amount: float, note: str = "") -> dict:
    cust = world.customer(customer_id)
    if cust is None:
        raise KeyError(customer_id)
    g = evaluate(customer_id, payee, amount)
    pid = new_id("pay")
    now = time.time()
    status = "paused" if g["fires"] else "executed"
    db.insert("requests", {
        "id": pid, "customer_id": customer_id, "channel": "app", "call_id": None, "action": "upi_payment",
        "details": {"payee": payee, "amount": amount, "note": note, "guard": g}, "tier": None,
        "policy": {"guard": g["fires"], "reqs": {}}, "status": status, "created_at": now, "updated_at": now, "cooloff_until": None,
    })
    db.audit(customer_id, "guard_fired" if g["fires"] else "payment_sent", pid, amount=amount, new_payee=g["new_payee"])
    if not g["fires"]:
        cust.balance -= amount
    family = [world.customer(f) for f in cust.family_circle]
    return {
        "payment_id": pid, "status": status, "guard": g, "amount_text": _inr(amount),
        "family": [{"id": f.id, "name": f.name.split()[0], "mobile": f.registered_mobile} for f in family if f],
    }


def ask_family(payment_id: str, family_id: str) -> dict:
    p = db.get("requests", payment_id)
    cust = world.customer(p["customer_id"])
    fam = world.customer(family_id)
    if fam is None or family_id not in cust.family_circle:
        raise PermissionError("not in this customer's Family Circle")
    d = p["details"]
    rel = "Mum" if cust.age > 50 else cust.name.split()[0]
    summary = {
        "question": f"Did you ask {rel} for {_inr(d['amount'])}?",
        "detail": f"{cust.name.split()[0]} is about to send {_inr(d['amount'])} to {d['payee']}, a new payee, just after a phone call.",
        "amount": d["amount"], "payee": d["payee"], "from_customer": cust.id,
    }
    db.update("requests", payment_id, {"status": "awaiting_family", "updated_at": time.time()})
    db.audit(cust.id, "family_ping_sent", payment_id, to=family_id)
    return passkeys.request_approval(payment_id, family_id, "family_ping", summary)


def on_family_decision(approval: dict) -> None:
    if approval["kind"] != "family_ping":
        return
    pid = approval["request_id"]
    p = db.get("requests", pid)
    if p is None or p["status"] not in ("awaiting_family", "paused"):
        return
    payer = p["customer_id"]
    if approval["status"] == "declined":
        db.update("requests", pid, {"status": "cancelled", "updated_at": time.time()})
        db.audit("family", "payment_cancelled_by_family", pid)
        case = cases.open_case(channel="app", customer_id=payer, request_id=pid, tier="RED",
                               reasons=["FAMILY_DECLINED"], scores={"amount": p["details"]["amount"]}, event="family_declined")
        report = prefill_1930(pid)
        hub.publish(f"app:{payer}", {"type": "payment", "payment_id": pid, "status": "cancelled",
                                     "message": f"{world.customer(approval['target_customer']).name.split()[0]} says they did not ask for this. We cancelled the payment.",
                                     "report": report, "case_id": case["id"]})
    elif approval["status"] == "approved":
        cust = world.customer(payer)
        cust.balance -= float(p["details"]["amount"])
        db.update("requests", pid, {"status": "executed", "updated_at": time.time()})
        db.audit("family", "payment_released_by_family", pid)
        hub.publish(f"app:{payer}", {"type": "payment", "payment_id": pid, "status": "executed",
                                     "message": f"{world.customer(approval['target_customer']).name.split()[0]} confirmed. Payment sent."})


def continue_anyway(payment_id: str) -> dict:
    p = db.get("requests", payment_id)
    if p["status"] not in ("paused", "awaiting_family"):
        return {"status": p["status"]}
    world.customer(p["customer_id"]).balance -= float(p["details"]["amount"])
    db.update("requests", payment_id, {"status": "executed", "updated_at": time.time()})
    db.audit(p["customer_id"], "payment_continued_after_pause", payment_id)
    return {"status": "executed"}


def cancel(payment_id: str) -> dict:
    db.update("requests", payment_id, {"status": "cancelled", "updated_at": time.time()})
    db.audit("customer", "payment_cancelled", payment_id)
    return {"status": "cancelled"}


def prefill_1930(payment_id: str) -> dict:
    p = db.get("requests", payment_id)
    cust = world.customer(p["customer_id"])
    d = p["details"]
    payload = {
        "helpline": "1930", "portal": "cybercrime.gov.in",
        "complainant": cust.name, "mobile": cust.registered_mobile,
        "category": "Online financial fraud > Impersonation (AI voice)",
        "amount_attempted": d["amount"], "payee_vpa": d["payee"],
        "description": "Received a call from someone sounding like a family member asking for urgent money. Family member confirmed they did not call.",
        "status": "prefilled, not submitted",
    }
    rid = new_id("ncrp")
    db.insert("reports", {"id": rid, "kind": "ncrp_1930_prefill", "case_id": None, "created_at": time.time(), "payload": payload})
    return {"id": rid, **payload}
