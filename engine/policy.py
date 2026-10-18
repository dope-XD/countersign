"""Policy engine: tier x request risk -> requirements, enforced server-side.

A request cannot be executed until every requirement is met. The agent console only
reflects this; it cannot route around it.
"""
from __future__ import annotations

import time
from pathlib import Path

import yaml

from engine.db import db, new_id
from engine.fusion import TIERS
from engine.hub import hub
from engine.mocks.world import DAY, world

_POLICY = yaml.safe_load((Path(__file__).parent / "policy.yaml").read_text(encoding="utf-8"))
ACTIONS: dict = _POLICY["actions"]
MATRIX: dict = _POLICY["matrix"]
SCRIPT: dict = _POLICY["script"]
OVERRIDE: dict = _POLICY["override"]


class PolicyError(Exception):
    pass


def cell(action: str, tier: str) -> dict:
    if action not in ACTIONS:
        raise PolicyError(f"unknown action {action}")
    return MATRIX[ACTIONS[action]["risk"]][tier]


def _reqs_for(action: str, tier: str, previous: dict | None = None) -> dict:
    reqs = {r: {"status": "pending"} for r in cell(action, tier)["requirements"]}
    if previous:
        # tiers only ratchet up during a request: keep progress, never drop a requirement
        for r, st in previous.items():
            reqs[r] = st
    return reqs


def create_request(customer_id: str, channel: str, action: str, details: dict, tier: str, call_id: str | None = None) -> dict:
    c = cell(action, tier)
    now = time.time()
    rid = new_id("req")
    policy = {
        "risk": ACTIONS[action]["risk"],
        "tier": tier,
        "note": c.get("note"),
        "no_phone_approval": bool(c.get("no_phone_approval")),
        "no_sensitive_details": bool(c.get("no_sensitive_details")),
        "reqs": _reqs_for(action, tier),
        "overrides": [],
    }
    db.insert(
        "requests",
        {
            "id": rid, "customer_id": customer_id, "channel": channel, "call_id": call_id, "action": action,
            "details": details, "tier": tier, "policy": policy, "status": "open",
            "created_at": now, "updated_at": now, "cooloff_until": None,
        },
    )
    db.audit("policy", "request_created", rid, action=action, tier=tier, channel=channel)
    req = get(rid)
    _auto_steps(req)
    return get(rid)


def get(rid: str) -> dict:
    r = db.get("requests", rid)
    if r is None:
        raise PolicyError("no such request")
    return r


def escalate(rid: str, new_tier: str) -> dict:
    """Called when the call's tier rises while a request is open."""
    r = get(rid)
    if r["status"] != "open" or TIERS.index(new_tier) <= TIERS.index(r["tier"]):
        return r
    c = cell(r["action"], new_tier)
    pol = r["policy"]
    pol["reqs"] = _reqs_for(r["action"], new_tier, pol["reqs"])
    pol["tier"] = new_tier
    pol["note"] = c.get("note")
    pol["no_phone_approval"] = pol["no_phone_approval"] or bool(c.get("no_phone_approval"))
    pol["no_sensitive_details"] = pol["no_sensitive_details"] or bool(c.get("no_sensitive_details"))
    db.update("requests", rid, {"tier": new_tier, "policy": pol, "updated_at": time.time()})
    db.audit("policy", "request_escalated", rid, tier=new_tier)
    r = get(rid)
    _auto_steps(r)
    return get(rid)


def _auto_steps(r: dict) -> None:
    pol = r["policy"]
    if "alert_customer" in pol["reqs"] and pol["reqs"]["alert_customer"]["status"] == "pending":
        cust = world.customer(r["customer_id"])
        label = ACTIONS[r["action"]]["label"].lower()
        hub.publish(
            f"app:{r['customer_id']}",
            {"type": "alert", "title": "Someone asked us to change your account",
             "body": f"A caller asked to {label}. We paused it. If this wasn't you, you don't need to do anything.",
             "request_id": r["id"]},
        )
        mark(r["id"], "alert_customer", "met", by="system", channel=f"app+sms {cust.registered_mobile if cust else ''}")


def mark(rid: str, requirement: str, status: str, by: str, **detail) -> dict:
    r = get(rid)
    pol = r["policy"]
    if requirement not in pol["reqs"]:
        raise PolicyError(f"{requirement} is not required for this request")
    pol["reqs"][requirement] = {"status": status, "by": by, "at": time.time(), **detail}
    cooloff = r["cooloff_until"]
    if requirement == "app_approval" and status == "met" and "cooloff_24h" in pol["reqs"]:
        cooloff = time.time() + DAY
        pol["reqs"]["cooloff_24h"] = {"status": "pending", "until": cooloff}
    new_status = r["status"]
    if status == "failed" and requirement in ("app_approval",):
        new_status = "declined"
    db.update("requests", rid, {"policy": pol, "cooloff_until": cooloff, "status": new_status, "updated_at": time.time()})
    db.audit(by, f"requirement_{status}", rid, requirement=requirement, **detail)
    return get(rid)


def override(rid: str, requirement: str, agent: str, reason: str) -> dict:
    r = get(rid)
    if r["tier"] not in OVERRIDE["allowed_tiers"]:
        raise PolicyError("Override is not available on RED.")
    if requirement not in OVERRIDE["waives"]:
        raise PolicyError(f"{requirement} cannot be overridden.")
    if not reason.strip():
        raise PolicyError("A reason is required.")
    r = mark(rid, requirement, "waived", by=agent, reason=reason)
    r["policy"]["overrides"].append({"requirement": requirement, "agent": agent, "reason": reason, "at": time.time()})
    db.update("requests", rid, {"policy": r["policy"]})
    return get(rid)


def decline_voice_check(rid: str, agent: str) -> dict:
    """Customer declines (or can't do) the voice check: it is replaced by app approval, never failed."""
    r = get(rid)
    pol = r["policy"]
    if "liveness" in pol["reqs"]:
        pol["reqs"]["liveness"] = {"status": "replaced", "by": agent, "at": time.time(), "with": "app_approval"}
        pol["reqs"].setdefault("app_approval", {"status": "pending"})
        db.update("requests", rid, {"policy": pol, "updated_at": time.time()})
        db.audit(agent, "liveness_replaced_by_app_approval", rid)
    return get(rid)


def missing(r: dict) -> list[str]:
    out = []
    now = time.time()
    for name, st in r["policy"]["reqs"].items():
        if name == "cooloff_24h":
            until = st.get("until") or r.get("cooloff_until")
            if not until or now < until:
                out.append(name)
        elif st["status"] not in ("met", "waived", "replaced"):
            out.append(name)
    return out


def execute(rid: str, actor: str) -> dict:
    r = get(rid)
    if r["status"] != "open":
        raise PolicyError(f"Request is {r['status']}.")
    need = missing(r)
    if need:
        raise PolicyError("Not allowed yet. Missing: " + ", ".join(need))
    _apply(r)
    db.update("requests", rid, {"status": "executed", "updated_at": time.time()})
    db.audit(actor, "request_executed", rid, action=r["action"])
    return get(rid)


def cancel(rid: str, actor: str, reason: str) -> dict:
    db.update("requests", rid, {"status": "cancelled", "updated_at": time.time()})
    db.audit(actor, "request_cancelled", rid, reason=reason)
    return get(rid)


def _apply(r: dict) -> None:
    cust = world.customer(r["customer_id"])
    d = r["details"] or {}
    if cust is None:
        return
    if r["action"] == "change_mobile" and d.get("new_mobile"):
        cust.registered_mobile = d["new_mobile"]
    elif r["action"] == "add_payee" and d.get("payee"):
        cust.known_payees.append(d["payee"])
    elif r["action"] == "raise_limit" and d.get("limit"):
        cust.usual_upi_max = float(d["limit"])
    elif r["action"] in ("large_transfer", "upi_payment") and d.get("amount"):
        cust.balance -= float(d["amount"])
