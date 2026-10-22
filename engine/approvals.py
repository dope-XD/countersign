"""Sending the app approval for a request: the same step whether the human agent clicks
"Send app approval" or the /try page's virtual agent asks for it."""

from __future__ import annotations

import time

from engine import policy
from engine.db import db
from engine.mocks.world import world
from engine.stepup import passkeys


def send_app_approval(rid: str, require_passkey: bool = True) -> dict:
    """Ask the account holder's phone "Did you ask us to ...?". Raises PolicyError when it can't be sent.

    require_passkey=False still sends it to a phone with no passkey; that phone can only decline
    (the /try page, where a judge may not have bound one yet)."""
    r = policy.get(rid)
    if r["status"] != "open":
        raise policy.PolicyError(f"request is {r['status']}")
    st = r["policy"]["reqs"].get("app_approval")
    if st is None:
        raise policy.PolicyError("this request doesn't need an app approval")
    if st["status"] == "sent":
        if passkeys.is_open(st["approval_id"]):
            raise policy.PolicyError("already waiting for the customer to answer")
        passkeys.expire(st["approval_id"])  # resend after the old one timed out
    elif st["status"] != "pending":
        raise policy.PolicyError(f"app approval is already {st['status']}")
    if require_passkey and not passkeys.credentials(r["customer_id"]):
        raise policy.PolicyError("No passkey on this account. The customer must approve at a branch or by video-KYC.")
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
    a = passkeys.request_approval(rid, r["customer_id"], "app_approval", summary)
    pol = r["policy"]
    pol["reqs"]["app_approval"] = {"status": "sent", "approval_id": a["id"], "at": time.time()}
    db.update("requests", rid, {"policy": pol, "updated_at": time.time()})
    return a
