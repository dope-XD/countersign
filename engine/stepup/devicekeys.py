"""Phone keys and transaction-bound approvals.

Each CS Bank app makes an EC P-256 key in the phone's Android Keystore when it signs up. The
private key never leaves the phone's secure hardware, and the phone only signs after a
fingerprint or screen-lock check. The server keeps the public key.

An approval's challenge is SHA-256 over the exact summary shown on the phone plus a nonce.
"Yes" is a signature over `approve:<approval id>:<challenge>`, so it proves the owner of that
phone approved *that* change. A cloned voice cannot produce it. "No" needs no signature:
anyone holding the phone may refuse.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import sqlite3
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from engine.db import db, new_id
from engine.hub import hub
from engine.mocks.world import DAY, world

APPROVAL_TTL = 300  # seconds an approval request stays open


class StepUpError(Exception):
    pass


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64(s: str) -> bytes:
    """Standard or URL-safe base64, padded or not (Android and Python differ)."""
    s = s.strip().replace("-", "+").replace("_", "/")
    return base64.b64decode(s + "=" * (-len(s) % 4), validate=True)


# ---------------------------------------------------------------- phone keys
def _load_key(der: bytes) -> ec.EllipticCurvePublicKey:
    try:
        key = serialization.load_der_public_key(der)
    except ValueError as e:
        raise StepUpError("that isn't a public key") from e
    if not isinstance(key, ec.EllipticCurvePublicKey) or key.curve.name != "secp256r1":
        raise StepUpError("the phone key must be EC P-256")
    return key


def register_device(customer_id: str, public_key_b64: str, label: str) -> dict:
    """Bind a phone to an account by its public key (X.509 SubjectPublicKeyInfo, DER, base64)."""
    cust = world.customer(customer_id)
    if cust is None:
        raise StepUpError("no such customer")
    if world.sim_swapped_within(cust.registered_mobile, 7 * DAY):
        # deck: a new device within 7 days of a SIM swap is itself high-risk
        db.audit("stepup", "device_blocked_sim_swap", customer_id)
        raise StepUpError("A SIM swap happened on your number in the last 7 days. Please register this phone at a branch.")
    try:
        der = unb64(public_key_b64)
    except (binascii.Error, ValueError) as e:
        raise StepUpError("the phone key isn't valid base64") from e
    _load_key(der)
    did = "dev_" + hashlib.sha256(der).hexdigest()[:16]
    try:
        db.insert(
            "credentials",
            {
                "id": did,
                "customer_id": customer_id,
                "public_key": der,
                "sign_count": 0,
                "transports": None,
                "device_label": label[:80],
                "created_at": time.time(),
                "kind": "device_key",
            },
        )
    except sqlite3.IntegrityError as e:
        raise StepUpError("this phone is already registered") from e
    db.audit(customer_id, "device_registered", did, device=label[:80])
    return {"device_id": did}


def devices(customer_id: str) -> list[dict]:
    return db.query("SELECT id, device_label, created_at FROM credentials WHERE customer_id=?", [customer_id])


def remove_devices(customer_id: str) -> None:
    db.execute("DELETE FROM credentials WHERE customer_id=?", [customer_id])
    db.audit(customer_id, "devices_removed", customer_id)


def signed_message(approval_id: str, challenge: str) -> bytes:
    """Exactly what the phone signs to say "Yes"."""
    return f"approve:{approval_id}:{challenge}".encode()


def _verify(customer_id: str, message: bytes, signature_b64: str) -> str:
    """The id of the customer's phone key that made this signature, else StepUpError."""
    try:
        sig = unb64(signature_b64)
    except (binascii.Error, ValueError) as e:
        raise StepUpError("signature isn't valid base64") from e
    for row in db.query("SELECT id, public_key FROM credentials WHERE customer_id=? AND kind='device_key'", [customer_id]):
        try:
            _load_key(row["public_key"]).verify(sig, message, ec.ECDSA(hashes.SHA256()))
            return row["id"]
        except InvalidSignature:
            continue
    raise StepUpError("signature could not be verified with this account's phone key")


# ---------------------------------------------------------------- approvals
def _bind(summary: dict, nonce: bytes) -> bytes:
    canon = json.dumps(summary, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(canon + nonce).digest()


def is_open(aid: str) -> bool:
    """Still waiting for the customer (pending and not past its time limit)."""
    a = db.get("approvals", aid)
    return bool(a) and a["status"] == "pending" and time.time() - a["created_at"] <= APPROVAL_TTL


def expire(aid: str) -> None:
    a = db.get("approvals", aid)
    if a and a["status"] == "pending":
        db.update("approvals", aid, {"status": "expired", "decided_at": time.time()})


def request_approval(request_id: str, target_customer: str, kind: str, summary: dict) -> dict:
    """kind: app_approval (the account holder), family_ping (a family member),
    call_check (a family member: "is it you on Mom's call?") or
    kill_switch_off (the account holder lifting their own kill switch)."""
    aid = new_id("apr")
    nonce = os.urandom(16)
    summary = {**summary, "approval_id": aid, "request_id": request_id, "issued_at": int(time.time())}
    challenge = _bind(summary, nonce)
    db.insert(
        "approvals",
        {
            "id": aid,
            "request_id": request_id,
            "kind": kind,
            "target_customer": target_customer,
            "challenge": b64u(challenge),
            "summary": summary,
            "status": "pending",
            "created_at": time.time(),
            "decided_at": None,
            "credential_id": None,
            "nonce": b64u(nonce),  # kept so the binding can be re-checked later
        },
    )
    db.audit("stepup", "approval_requested", aid, request_id=request_id, kind=kind, target=target_customer)
    hub.publish(f"app:{target_customer}", {"type": "approval", "approval": public_approval(aid)})
    return public_approval(aid)


def public_approval(aid: str) -> dict:
    a = db.get("approvals", aid)
    if a is None:
        raise StepUpError("no such approval")
    out = {k: a[k] for k in ("id", "request_id", "kind", "target_customer", "summary", "status", "created_at", "decided_at", "challenge")}
    target = world.customer(a["target_customer"])
    out["deliver"] = target.check_channel if target else "notify"  # ring or notify, as the target chose at sign-up
    out["expires_at"] = a["created_at"] + APPROVAL_TTL
    for k in ("from", "question", "detail"):  # the ring screen's text (docs/agents/CONTRACT.md)
        out[k] = (a["summary"] or {}).get(k, "")
    return out


def pending_for(customer_id: str) -> list[dict]:
    rows = db.query(
        "SELECT id FROM approvals WHERE target_customer=? AND status='pending' AND created_at>? ORDER BY created_at DESC",
        [customer_id, time.time() - APPROVAL_TTL],
    )
    return [public_approval(r["id"]) for r in rows]


def decide(aid: str, decision: str, signature: str | None) -> dict:
    """'approve' needs the target's phone signature over this approval's challenge; 'decline' needs none."""
    a = db.get("approvals", aid)
    if a is None:
        raise StepUpError("no such approval")
    if a["status"] != "pending":
        raise StepUpError(f"already {a['status']}")
    if time.time() - a["created_at"] > APPROVAL_TTL:
        expire(aid)
        raise StepUpError("approval expired")
    cred_id = None
    signed = None
    if decision == "approve":
        if not signature:
            raise StepUpError("signature required")
        cred_id = _verify(a["target_customer"], signed_message(aid, a["challenge"]), signature)
        status = "approved"
        signed = {"device_id": cred_id, "signature": signature, "verified_at": time.time()}
    elif decision == "decline":
        status = "declined"
    else:
        raise StepUpError("decision must be approve or decline")
    db.update("approvals", aid, {"status": status, "decided_at": time.time(), "credential_id": cred_id, "assertion": signed})
    db.audit(a["target_customer"], f"approval_{status}", aid, request_id=a["request_id"], device=cred_id)
    result = public_approval(aid)
    hub.publish("stepup", {"type": "approval_decided", "approval": result})
    return result


def binding_evidence(aid: str) -> dict:
    """Re-check, after the fact, that an approval's signature covers exactly the request the
    customer was shown: the challenge is sha256(summary + nonce), and the stored signature
    still verifies against the phone's key."""
    a = db.get("approvals", aid)
    if a is None:
        raise StepUpError("no such approval")
    out = {"approval_id": aid, "status": a["status"], "summary": a["summary"], "checks": {}}
    challenge = _bind(a["summary"], unb64(a["nonce"]))
    out["checks"]["challenge_is_hash_of_summary"] = b64u(challenge) == a["challenge"]
    signed = a.get("assertion")
    if a["status"] != "approved" or not signed:
        return out
    try:
        _verify(a["target_customer"], signed_message(aid, a["challenge"]), signed["signature"])
        out["checks"]["signature_verifies"] = True
    except StepUpError:
        out["checks"]["signature_verifies"] = False
    return out
