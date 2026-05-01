from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from common.config import get_settings


@dataclass
class CryptoBox:
    key: bytes

    @classmethod
    def from_env(cls) -> "CryptoBox":
        s = get_settings()
        if not s.enc_shared_key_b64:
            raise ValueError("ENC_SHARED_KEY_BASE64 not set")
        key = base64.b64decode(s.enc_shared_key_b64)
        if len(key) not in (16, 24, 32):
            raise ValueError("ENC_SHARED_KEY_BASE64 must be 16/24/32 bytes")
        return cls(key=key)

    def encrypt(self, data: bytes, aad: Optional[bytes] = None) -> bytes:
        nonce = os.urandom(12)
        aes = AESGCM(self.key)
        ct = aes.encrypt(nonce, data, aad)
        return nonce + ct

    def decrypt(self, data: bytes, aad: Optional[bytes] = None) -> bytes:
        nonce = data[:12]
        ct = data[12:]
        aes = AESGCM(self.key)
        return aes.decrypt(nonce, ct, aad)
