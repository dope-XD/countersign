"""A software stand-in for the CS Bank app's Keystore key, for the call simulator and tests only.

It makes an EC P-256 key and signs approvals exactly as the phone does (SHA256withECDSA over
`approve:<approval id>:<challenge>`), so simulated genuine customers go through the same
server-side signature check as a real phone. Never used outside ml/eval and engine/tests.
"""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec


class SoftDevice:
    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.token = ""  # the device token the server returns when this key is registered

    @property
    def public_key(self) -> str:
        der = self.key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        return base64.b64encode(der).decode()

    def sign(self, approval: dict) -> str:
        """The signature the app sends with "Yes" for this approval (as the server returns it)."""
        msg = f"approve:{approval['id']}:{approval['challenge']}".encode()
        return base64.b64encode(self.key.sign(msg, ec.ECDSA(hashes.SHA256()))).decode()
