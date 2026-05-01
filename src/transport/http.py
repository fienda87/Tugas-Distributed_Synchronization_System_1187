from __future__ import annotations

import json
from typing import Optional

import aiohttp

from common.config import get_settings
from common.crypto import CryptoBox


class HttpClient:
    def __init__(self) -> None:
        self._crypto = None
        s = get_settings()
        self._api_key = s.internal_api_key
        if s.inter_node_enc:
            self._crypto = CryptoBox.from_env()

    async def post_json(self, url: str, payload: dict, timeout: float = 2.0) -> dict:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["X-API-Key"] = self._api_key
        if self._crypto:
            body = self._crypto.encrypt(body)
            headers["X-ENC"] = "aesgcm"
        async with aiohttp.ClientSession() as sess:
            async with sess.post(url, data=body, headers=headers, timeout=timeout) as r:
                r.raise_for_status()
                return await r.json()

    async def get_json(self, url: str, timeout: float = 2.0) -> dict:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(url, timeout=timeout) as r:
                r.raise_for_status()
                return await r.json()


HTTP = HttpClient()
