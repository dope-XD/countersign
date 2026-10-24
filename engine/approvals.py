"""The app approval for a change asked for on a call: sending it to the account holder's phone,
and what their "Yes" or "No" does. The same steps whether the human agent clicks "Send app
approval" or the virtual agent asks for it."""

from __future__ import annotations

import json
import time

from engine import cases, indiacall, policy
from engine.config import settings
from engine.db import db
from engine.hub import hub
from engine.mocks.world import world
from engine.session import calls
from engine.stepup import devicekeys


def send_app_approval(rid: str) -> dict:
    """Ask the account holder's phone "Did you ask us to ...?". Raises PolicyError when it can't be sent."""
    r = policy.get(rid)
    if r["status"] != "open":
        raise policy.PolicyError(f"request is {r['status']}")
    st = r["policy"]["reqs"].get("app_approval")
    if st is None:
        raise policy.PolicyError("this request doesn't need an app approval")
    if st["status"] == "sent":
        if devicekeys.is_open(st["approval_id"]):
            raise policy.PolicyError("already waiting for the customer to answer")
        devicekeys.expire(st["approval_id"])  # resend after the old one timed out
    elif st["status"] != "pending":
        raise policy.PolicyError(f"app approval is already {st['status']}")
    if not devicekeys.devices(r["customer_id"]):
        raise policy.PolicyError("This account has no phone with the CS Bank app. The customer must approve at a branch or by video-KYC.")
    cust = world.customer(r["customer_id"])
    label = policy.ACTIONS[r["action"]]["label"]
    detail = ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in (r["details"] or {}).items())
    summary = {
        "question": f"Did you ask us to: {label}?",
        "detail": detail,
        "action": r["action"],
        "channel": "phone call to the bank",
        "customer": cust.name if cust else r["customer_id"],
    }
    a = devicekeys.request_approval(rid, r["customer_id"], "app_approval", summary)
    pol = r["policy"]
    pol["reqs"]["app_approval"] = {"status": "sent", "approval_id": a["id"], "at": time.time()}
    db.update("requests", rid, {"policy": pol, "updated_at": time.time()})
    publish_call(r.get("call_id"))
    return a


def publish_call(call_id: str | None) -> None:
    cs = calls.get(call_id) if call_id else None
    if cs:
        hub.publish(f"call:{cs.id}", {"type": "state", "call": cs.public()})


def on_decision(a: dict) -> None:
    """The account holder answered an app approval on their phone."""
    rid = a["request_id"]
    r = policy.get(rid)
    if r["status"] != "open":
        return  # e.g. already cancelled by the fraud desk: the answer is recorded, nothing changes
    if a["status"] == "approved":
        r = policy.mark(rid, "app_approval", "met", by=a["target_customer"], approval_id=a["id"])
        _record_human_lag(r.get("call_id"))
    else:
        r = policy.mark(rid, "app_approval", "failed", by=a["target_customer"], approval_id=a["id"])
        cs = calls.get(r["call_id"]) if r.get("call_id") else None
        if cs:
            cs.ensure_case("customer_declined_in_app")
        else:
            cases.open_case(channel="contact_centre", customer_id=r["customer_id"], request_id=rid, tier=r["tier"], event="customer_declined_in_app")
        hub.publish(
            f"app:{a['target_customer']}",
            {"type": "alert", "title": "Thanks. Nothing was changed.", "body": "Our fraud team has the case. You can call us on the number on your card."},
        )
    publish_call(r.get("call_id"))


def _record_human_lag(call_id: str | None) -> None:
    """An approved request means the caller was the real customer, so their liveness reply
    delay is a genuine human sample for the IndiaCall simulator."""
    cs = calls.get(call_id) if call_id else None
    if not cs or not cs.liveness or cs.liveness.get("lag_s") is None or settings.eval_mode:
        return
    p = indiacall.ROOT / "human_lags.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    lags = json.loads(p.read_text()) if p.exists() else []
    lags.append(cs.liveness["lag_s"])
    p.write_text(json.dumps(lags))
