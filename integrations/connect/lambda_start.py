"""Lambda for the Countersign contact flow: tell the engine a call's audio is streaming.

Runs from an "Invoke AWS Lambda function" block placed after "Start media streaming".
Reads the contact's Kinesis Video Streams position from the event and POSTs it to
``$ENGINE_URL/api/ingest/connect/start``:

    {"contactId", "initialContactId", "instanceArn", "streamArn", "startFragment",
     "startTimestamp", "attributes", "sentAt"}

The body is signed with HMAC-SHA256 over the exact bytes sent, in the header
``X-Countersign-Signature: sha256=<hex>``. ``sentAt`` (epoch ms) is inside the signed
body so the engine can reject replays older than a few seconds (see ``verify``).

Environment:
    ENGINE_URL            base URL of the engine, e.g. https://<name>.ngrok-free.app (required)
    CONNECT_HMAC_SECRET   shared secret, same value as the engine's (required)
    ENGINE_PATH           default /api/ingest/connect/start
    ENGINE_TIMEOUT_S      default 3; Connect waits at most 8 s for the whole block

Stdlib only, so the deployment package is this one file (handler: lambda_start.handler).
It never raises: Connect gets a flat string map back and the flow carries on to the
queue either way, so a down engine cannot strand a caller.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
import urllib.error
import urllib.request

SIGNATURE_HEADER = "X-Countersign-Signature"
DEFAULT_PATH = "/api/ingest/connect/start"
DEFAULT_TIMEOUT_S = 3.0
MAX_SKEW_MS = 30_000

log = logging.getLogger("countersign.connect")
log.setLevel(logging.INFO)


def sign(body: bytes, secret: str | bytes) -> str:
    """Header value for ``body``: ``sha256=`` + hex HMAC-SHA256 under ``secret``."""
    key = secret.encode("utf-8") if isinstance(secret, str) else secret
    return "sha256=" + hmac.new(key, body, hashlib.sha256).hexdigest()


def verify(body: bytes, header: str | None, secret: str | bytes, now_ms: int | None = None, max_skew_ms: int = MAX_SKEW_MS) -> bool:
    """Engine-side check: signature matches (constant time) and ``sentAt`` is fresh."""
    if not header or not hmac.compare_digest(sign(body, secret), header):
        return False
    try:
        sent_at = int(json.loads(body)["sentAt"])
    except (ValueError, KeyError, TypeError):
        return False
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    return abs(now_ms - sent_at) <= max_skew_ms


def build_payload(event: dict, now_ms: int | None = None) -> dict:
    """Pick what the engine needs out of a Connect ContactFlowEvent."""
    data = (event.get("Details") or {}).get("ContactData") or {}
    audio = ((data.get("MediaStreams") or {}).get("Customer") or {}).get("Audio") or {}
    return {
        "contactId": data.get("ContactId"),
        "initialContactId": data.get("InitialContactId"),
        "instanceArn": data.get("InstanceARN"),
        "streamArn": audio.get("StreamARN"),
        "startFragment": audio.get("StartFragmentNumber"),
        "startTimestamp": audio.get("StartTimestamp"),
        "attributes": data.get("Attributes") or {},
        "sentAt": int(time.time() * 1000) if now_ms is None else now_ms,
    }


def post(url: str, payload: dict, secret: str, timeout: float) -> int:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", SIGNATURE_HEADER: sign(body, secret), "User-Agent": "countersign-connect-lambda/1"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status


def handler(event: dict, context=None) -> dict:
    """Connect entry point. Returns a flat map of [A-Za-z0-9_-] strings, as Connect requires."""
    base = os.environ.get("ENGINE_URL", "").rstrip("/")
    secret = os.environ.get("CONNECT_HMAC_SECRET", "")
    if not base or not secret:
        log.error("ENGINE_URL or CONNECT_HMAC_SECRET is not set")
        return {"countersign": "not_configured"}

    payload = build_payload(event)
    if not payload["contactId"] or not payload["streamArn"]:
        # Start media streaming failed or ran after this block: nothing for the engine to pull.
        log.warning("no media stream on contact %s", payload["contactId"])
        return {"countersign": "no_stream"}

    log.info("contact %s stream %s start fragment %s", payload["contactId"], payload["streamArn"], payload["startFragment"])
    url = base + os.environ.get("ENGINE_PATH", DEFAULT_PATH)
    timeout = float(os.environ.get("ENGINE_TIMEOUT_S", DEFAULT_TIMEOUT_S))
    try:
        status = post(url, payload, secret, timeout)
    except urllib.error.HTTPError as e:
        log.error("engine answered %s for contact %s", e.code, payload["contactId"])
        return {"countersign": "error", "status": f"http_{e.code}"}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        log.error("engine unreachable for contact %s: %s", payload["contactId"], e)
        return {"countersign": "error", "status": "unreachable"}
    log.info("engine accepted contact %s: %s", payload["contactId"], status)
    return {"countersign": "ok", "status": f"http_{status}"}
