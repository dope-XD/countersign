"""Passkey enrolment and transaction-bound approvals (WebAuthn).

The approval challenge is SHA-256 over the exact request summary shown on the phone,
so the signature proves the customer approved *that* change, on a device the caller
doesn't hold. A cloned voice cannot produce it.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from engine.config import settings
from engine.db import db, new_id
from engine.hub import hub
from engine.mocks.world import DAY, world

_reg_challenges: dict[str, tuple[bytes, float]] = {}
APPROVAL_TTL = 300  # seconds an approval request stays open


class StepUpError(Exception):
    pass


LOCAL_HOSTS = ("localhost", "127.0.0.1")


def _rp_id(host: str | None) -> str:
    if settings.rp_id != "auto":
        return settings.rp_id
    if not host:
        raise StepUpError("cannot work out the passkey domain for this request")
    return host.split(":")[0]


def _origins(host: str | None) -> list[str]:
    """Origins a signature may come from. In auto mode they are derived from the same Host
    the RP ID comes from, never echoed from the request's Origin header."""
    allowed = list(settings.origins)
    if settings.rp_id == "auto" and host:
        allowed.append(f"https://{host}")
        if host.split(":")[0] in LOCAL_HOSTS:
            allowed.append(f"http://{host}")
    return allowed


# ---------------------------------------------------------------- enrolment
def registration_options(customer_id: str, host: str | None = None) -> str:
    cust = world.customer(customer_id)
    if cust is None:
        raise StepUpError("unknown customer")
    if world.sim_swapped_within(cust.registered_mobile, 7 * DAY):
        # deck: new device/passkey within 7 days of a SIM swap is itself high-risk
        db.audit("stepup", "enrol_blocked_sim_swap", customer_id)
        raise StepUpError("A SIM swap happened on your number in the last 7 days. Please enrol this phone at a branch.")
    existing = db.query("SELECT id FROM credentials WHERE customer_id=?", [customer_id])
    opts = generate_registration_options(
        rp_id=_rp_id(host),
        rp_name=settings.rp_name,
        user_id=customer_id.encode(),
        user_name=cust.upi_id,
        user_display_name=cust.name,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(c["id"])) for c in existing],
    )
    _reg_challenges[customer_id] = (opts.challenge, time.time())
    return options_to_json(opts)


def verify_registration(customer_id: str, credential: dict, device_label: str, host: str | None) -> dict:
    ch = _reg_challenges.pop(customer_id, None)
    if ch is None or time.time() - ch[1] > 300:
        raise StepUpError("enrolment expired, try again")
    try:
        v = verify_registration_response(
            credential=credential,
            expected_challenge=ch[0],
            expected_rp_id=_rp_id(host),
            expected_origin=_origins(host),
            require_user_verification=True,
        )
    except WebAuthnException as e:
        db.audit("stepup", "enrol_rejected", customer_id, error=str(e))
        raise StepUpError(f"passkey could not be verified: {e}") from e
    cred_id = bytes_to_base64url(v.credential_id)
    try:
        db.insert(
            "credentials",
            {
                "id": cred_id,
                "customer_id": customer_id,
                "public_key": v.credential_public_key,
                "sign_count": v.sign_count,
                "transports": credential.get("response", {}).get("transports") or [],
                "device_label": device_label[:80],
                "created_at": time.time(),
            },
        )
    except sqlite3.IntegrityError as e:
        raise StepUpError("this passkey is already registered") from e
    db.audit(customer_id, "passkey_enrolled", cred_id, device=device_label[:80])
    return {"credential_id": cred_id}


def credentials(customer_id: str) -> list[dict]:
    return db.query("SELECT id, device_label, created_at FROM credentials WHERE customer_id=?", [customer_id])


def is_open(aid: str) -> bool:
    """Still waiting for the customer (pending and not past its time limit)."""
    a = db.get("approvals", aid)
    return bool(a) and a["status"] == "pending" and time.time() - a["created_at"] <= APPROVAL_TTL


def expire(aid: str) -> None:
    a = db.get("approvals", aid)
    if a and a["status"] == "pending":
        db.update("approvals", aid, {"status": "expired", "decided_at": time.time()})


def remove_credentials(customer_id: str) -> None:
    db.execute("DELETE FROM credentials WHERE customer_id=?", [customer_id])
    db.audit(customer_id, "passkeys_removed", customer_id)


# ---------------------------------------------------------------- approvals
def _bind(summary: dict, nonce: bytes) -> bytes:
    canon = json.dumps(summary, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(canon + nonce).digest()


def request_approval(request_id: str, target_customer: str, kind: str, summary: dict) -> dict:
    """kind: app_approval (the account holder) or family_ping (a Family Circle contact)."""
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
            "challenge": bytes_to_base64url(challenge),
            "summary": summary,
            "status": "pending",
            "created_at": time.time(),
            "decided_at": None,
            "credential_id": None,
        },
    )
    db.audit("stepup", "approval_requested", aid, request_id=request_id, kind=kind, target=target_customer)
    hub.publish(f"app:{target_customer}", {"type": "approval", "approval": public_approval(aid)})
    return public_approval(aid)


def public_approval(aid: str) -> dict:
    a = db.get("approvals", aid)
    if a is None:
        raise StepUpError("no such approval")
    return {k: a[k] for k in ("id", "request_id", "kind", "target_customer", "summary", "status", "created_at", "decided_at")}


def pending_for(customer_id: str) -> list[dict]:
    rows = db.query(
        "SELECT id FROM approvals WHERE target_customer=? AND status='pending' AND created_at>? ORDER BY created_at DESC",
        [customer_id, time.time() - APPROVAL_TTL],
    )
    return [public_approval(r["id"]) for r in rows]


def assertion_options(aid: str, host: str | None) -> str:
    a = db.get("approvals", aid)
    if a is None or a["status"] != "pending":
        raise StepUpError("approval is not pending")
    creds = db.query("SELECT id, transports FROM credentials WHERE customer_id=?", [a["target_customer"]])
    if not creds:
        raise StepUpError("no passkey enrolled on this account")
    opts = generate_authentication_options(
        rp_id=_rp_id(host),
        challenge=base64url_to_bytes(a["challenge"]),
        allow_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(c["id"])) for c in creds],
        user_verification=UserVerificationRequirement.REQUIRED,
        timeout=120000,
    )
    return options_to_json(opts)


def decide(aid: str, decision: str, credential: dict | None, host: str | None) -> dict:
    """decision 'approve' needs a valid passkey assertion over this approval's challenge.
    'decline' needs none: anyone holding the phone may refuse."""
    a = db.get("approvals", aid)
    if a is None:
        raise StepUpError("no such approval")
    if a["status"] != "pending":
        raise StepUpError(f"already {a['status']}")
    if time.time() - a["created_at"] > APPROVAL_TTL:
        expire(aid)
        raise StepUpError("approval expired")
    cred_id = None
    if decision == "approve":
        if not credential:
            raise StepUpError("signature required")
        cred_id = credential.get("id")
        row = db.get("credentials", cred_id)
        if row is None or row["customer_id"] != a["target_customer"]:
            db.audit("stepup", "approval_bad_credential", aid)
            raise StepUpError("this passkey is not registered to the account")
        try:
            v = verify_authentication_response(
                credential=credential,
                expected_challenge=base64url_to_bytes(a["challenge"]),
                expected_rp_id=_rp_id(host),
                expected_origin=_origins(host),
                credential_public_key=row["public_key"],
                credential_current_sign_count=row["sign_count"],
                require_user_verification=True,
            )
        except WebAuthnException as e:
            db.audit("stepup", "approval_bad_signature", aid, error=str(e))
            raise StepUpError(f"signature could not be verified: {e}") from e
        db.execute("UPDATE credentials SET sign_count=? WHERE id=?", [v.new_sign_count, cred_id])
        status = "approved"
    elif decision == "decline":
        status = "declined"
    else:
        raise StepUpError("decision must be approve or decline")
    db.update("approvals", aid, {"status": status, "decided_at": time.time(), "credential_id": cred_id})
    db.audit(a["target_customer"], f"approval_{status}", aid, request_id=a["request_id"], credential=cred_id)
    result = public_approval(aid)
    hub.publish("stepup", {"type": "approval_decided", "approval": result})
    return result
