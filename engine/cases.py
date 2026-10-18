"""Fraud cases, encrypted evidence clips and reporting (NCRP/1930, DoT DIP)."""
from __future__ import annotations

import hashlib
import io
import os
import secrets
import time
import wave

import numpy as np
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from engine.config import settings
from engine.db import db, new_id
from engine.hub import hub

EVIDENCE_DIR = settings.runtime_dir / "evidence"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)


def _key() -> bytes:
    """Mock KMS. In a bank this is a managed KMS key; here an env var or a local key file."""
    if settings.evidence_key_hex:
        return bytes.fromhex(settings.evidence_key_hex)
    kf = settings.runtime_dir / "kms.key"
    if not kf.exists():
        kf.write_text(secrets.token_hex(32))
    return bytes.fromhex(kf.read_text().strip())


def _wav_bytes(x: np.ndarray, sr: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
    return buf.getvalue()


def store_clip(case_id: str, audio16k: np.ndarray) -> str:
    nonce = os.urandom(12)
    ct = AESGCM(_key()).encrypt(nonce, _wav_bytes(audio16k, 16000), case_id.encode())
    path = EVIDENCE_DIR / f"{case_id}.bin"
    path.write_bytes(nonce + ct)
    return str(path)


def read_clip(case_id: str, actor: str) -> bytes:
    c = db.get("cases", case_id)
    if not c or not c.get("clip_path") or not os.path.exists(c["clip_path"]):
        raise FileNotFoundError("no clip")
    blob = open(c["clip_path"], "rb").read()
    db.audit(actor, "clip_played", case_id)  # every play is logged
    return AESGCM(_key()).decrypt(blob[:12], blob[12:], case_id.encode())


def audio_hash(audio16k: np.ndarray) -> str:
    """Coarse hash added to the replay list on confirmed fraud."""
    x = audio16k[: 16000 * 4]
    x = x[: len(x) // 400 * 400]
    if len(x) < 800:
        return ""
    spec = np.abs(np.fft.rfft(x.reshape(-1, 400) * np.hanning(400), axis=1))
    bands = spec[:, 5:150].reshape(spec.shape[0], -1, 5).mean(axis=2)
    bits = (np.diff(bands, axis=1) > 0).astype(np.uint8)
    return hashlib.sha256(np.packbits(bits).tobytes()).hexdigest()[:32]


def open_case(*, channel: str, customer_id: str | None, call_id: str | None = None, request_id: str | None = None,
              tier: str | None = None, reasons: list[str] | None = None, scores: dict | None = None,
              model_version: str | None = None, event: str = "opened") -> dict:
    existing = None
    if call_id:
        existing = next(iter(db.query("SELECT * FROM cases WHERE call_id=? AND status='open'", [call_id])), None)
    elif request_id:
        existing = next(iter(db.query("SELECT * FROM cases WHERE request_id=? AND status='open'", [request_id])), None)
    if existing:
        patch = {}
        if tier:
            patch.update({"tier": tier, "reasons": reasons, "scores": scores})
        # a case can open before the agent has identified the customer or logged the request
        if customer_id and not existing.get("customer_id"):
            patch["customer_id"] = customer_id
        if request_id and not existing.get("request_id"):
            patch["request_id"] = request_id
        if patch:
            db.update("cases", existing["id"], patch)
        add_event(existing["id"], event, tier=tier, reasons=reasons)
        return db.get("cases", existing["id"])
    cid = new_id("case")
    db.insert("cases", {
        "id": cid, "call_id": call_id, "request_id": request_id, "customer_id": customer_id, "channel": channel,
        "opened_at": time.time(), "status": "open", "tier": tier, "reasons": reasons or [], "scores": scores or {},
        "model_version": model_version, "timeline": [{"t": time.time(), "event": event, "tier": tier, "reasons": reasons}],
        "clip_path": None, "clip_expires": None, "outcome": None,
    })
    db.audit("system", "case_opened", cid, channel=channel, tier=tier)
    hub.publish("desk", {"type": "case", "case": db.get("cases", cid)})
    return db.get("cases", cid)


def add_event(case_id: str, event: str, **detail) -> None:
    c = db.get("cases", case_id)
    if not c:
        return
    tl = c["timeline"] or []
    tl.append({"t": time.time(), "event": event, **{k: v for k, v in detail.items() if v is not None}})
    db.update("cases", case_id, {"timeline": tl})
    hub.publish("desk", {"type": "case", "case": db.get("cases", case_id)})


def attach_clip(case_id: str, audio16k: np.ndarray) -> None:
    c = db.get("cases", case_id)
    if not c or c.get("clip_path"):
        return
    path = store_clip(case_id, audio16k[-int(settings.evidence_seconds * 16000):])
    db.update("cases", case_id, {"clip_path": path, "clip_expires": time.time() + settings.evidence_retention_days * 86400})
    add_event(case_id, "evidence_clip_encrypted", seconds=round(min(len(audio16k) / 16000, settings.evidence_seconds), 1))


def resolve(case_id: str, outcome: str, analyst: str, note: str = "") -> dict:
    """outcome: fraud_confirmed | false_alarm | callback"""
    c = db.get("cases", case_id)
    if not c:
        raise KeyError(case_id)
    status = "closed" if outcome in ("fraud_confirmed", "false_alarm") else "open"
    db.update("cases", case_id, {"outcome": outcome, "status": status})
    add_event(case_id, outcome, analyst=analyst, note=note or None)
    db.audit(analyst, f"case_{outcome}", case_id, note=note)
    if outcome == "fraud_confirmed":
        _report(case_id, "ncrp_1930", {"summary": "Voice-clone impersonation attempt", "reasons": c["reasons"], "customer": c["customer_id"]})
        if (c.get("scores") or {}).get("caller_cli"):
            _report(case_id, "dot_dip", {"number": c["scores"]["caller_cli"], "category": "financial fraud"})
        if c.get("clip_path"):
            try:
                raw = read_clip(case_id, analyst)
                pcm = np.frombuffer(raw[44:], dtype=np.int16).astype(np.float32) / 32768
                db.execute("INSERT OR IGNORE INTO replay_hashes (hash, case_id, created_at) VALUES (?,?,?)",
                           [audio_hash(pcm), case_id, time.time()])
            except Exception:
                pass
    if status == "closed" and c.get("clip_path") and outcome == "false_alarm":
        purge_clip(case_id, "case closed as false alarm")
    return db.get("cases", case_id)


def _report(case_id: str, kind: str, payload: dict) -> None:
    rid = new_id(kind)
    db.insert("reports", {"id": rid, "kind": kind, "case_id": case_id, "created_at": time.time(), "payload": payload})
    add_event(case_id, f"report_{kind}", report_id=rid)


def purge_clip(case_id: str, why: str) -> None:
    c = db.get("cases", case_id)
    if c and c.get("clip_path") and os.path.exists(c["clip_path"]):
        os.remove(c["clip_path"])
    db.update("cases", case_id, {"clip_path": None, "clip_expires": None})
    db.audit("system", "clip_deleted", case_id, why=why)


def purge_expired() -> int:
    n = 0
    for c in db.query("SELECT id FROM cases WHERE clip_expires IS NOT NULL AND clip_expires < ?", [time.time()]):
        purge_clip(c["id"], "30-day retention")
        n += 1
    return n
