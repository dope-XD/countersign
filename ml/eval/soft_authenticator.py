"""A software passkey for the call simulator only.

It produces real WebAuthn registration and assertion responses (P-256, "none"
attestation) so simulated genuine customers go through exactly the same server-side
signature checks as a phone. Never used outside ml/eval.
"""
from __future__ import annotations

import hashlib
import json
import os
import struct

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url


class SoftAuthenticator:
    def __init__(self, rp_id: str, origin: str):
        self.rp_id = rp_id
        self.origin = origin
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.cred_id = os.urandom(32)
        self.count = 0

    def _client_data(self, kind: str, challenge_b64: str) -> bytes:
        return json.dumps({"type": kind, "challenge": challenge_b64, "origin": self.origin, "crossOrigin": False}, separators=(",", ":")).encode()

    def _cose(self) -> bytes:
        nums = self.key.public_key().public_numbers()
        return cbor2.dumps({1: 2, 3: -7, -1: 1, -2: nums.x.to_bytes(32, "big"), -3: nums.y.to_bytes(32, "big")})

    def register(self, options: dict) -> dict:
        cd = self._client_data("webauthn.create", options["challenge"])
        auth = (
            hashlib.sha256(self.rp_id.encode()).digest()
            + bytes([0x45])
            + struct.pack(">I", self.count)
            + b"\x00" * 16
            + struct.pack(">H", len(self.cred_id))
            + self.cred_id
            + self._cose()
        )
        att = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth})
        cid = bytes_to_base64url(self.cred_id)
        return {
            "id": cid, "rawId": cid, "type": "public-key", "authenticatorAttachment": "platform", "clientExtensionResults": {},
            "response": {"clientDataJSON": bytes_to_base64url(cd), "attestationObject": bytes_to_base64url(att), "transports": ["internal"]},
        }

    def assert_(self, options: dict, user_handle: bytes) -> dict:
        self.count += 1
        cd = self._client_data("webauthn.get", options["challenge"])
        auth = hashlib.sha256(self.rp_id.encode()).digest() + bytes([0x05]) + struct.pack(">I", self.count)
        sig = self.key.sign(auth + hashlib.sha256(cd).digest(), ec.ECDSA(hashes.SHA256()))
        cid = bytes_to_base64url(self.cred_id)
        return {
            "id": cid, "rawId": cid, "type": "public-key", "authenticatorAttachment": "platform", "clientExtensionResults": {},
            "response": {
                "clientDataJSON": bytes_to_base64url(cd), "authenticatorData": bytes_to_base64url(auth),
                "signature": bytes_to_base64url(sig), "userHandle": bytes_to_base64url(user_handle),
            },
        }


def challenge_bytes(options: dict) -> bytes:
    return base64url_to_bytes(options["challenge"])
