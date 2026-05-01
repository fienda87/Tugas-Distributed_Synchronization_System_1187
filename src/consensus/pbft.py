from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from dataclasses import dataclass
from typing import Dict, Optional

from fastapi import APIRouter, Body, Depends

from common.config import get_settings
from common.security import require_role
from transport.http import HTTP


@dataclass
class PbftMsg:
    view: int
    seq: int
    digest: str
    client_req: dict


class PbftNode:
    def __init__(self, node_id: str, peers: list[str]):
        self.node_id = node_id
        self.peers = peers
        self.view = 0
        self.seq = 0
        self.prepared: Dict[str, set[str]] = {}
        self.committed: Dict[str, set[str]] = {}
        self.decided: Dict[str, dict] = {}
        self._pending: Dict[str, asyncio.Future] = {}

    def _digest(self, payload: dict) -> str:
        raw = str(sorted(payload.items())).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    async def pre_prepare(self, client_req: dict) -> dict:
        self.seq += 1
        dig = self._digest(client_req)
        msg = {
            "view": self.view,
            "seq": self.seq,
            "digest": dig,
            "client_req": client_req,
            "leader": self.node_id,
        }
        fut = asyncio.get_running_loop().create_future()
        self._pending[dig] = fut
        await asyncio.gather(
            *[HTTP.post_json(f"{p}/pbft/prepare", msg, timeout=1.5) for p in self.peers],
            return_exceptions=True,
        )
        # leader self prepare
        await self.on_prepare({"digest": dig, "leader": self.node_id})

        try:
            res = await asyncio.wait_for(fut, timeout=3.0)
        except asyncio.TimeoutError:
            res = {"accepted": True, "digest": dig, "seq": self.seq, "decided": False}
        return res

    async def on_prepare(self, body: dict) -> dict:
        dig = body["digest"]
        self.prepared.setdefault(dig, set()).add(body.get("leader", "unknown"))
        self.prepared[dig].add(self.node_id)
        if len(self.prepared[dig]) >= self.quorum():
            await asyncio.gather(
                *[
                    HTTP.post_json(f"{p}/pbft/commit", {"digest": dig, "leader": self.node_id}, timeout=1.5)
                    for p in self.peers
                ],
                return_exceptions=True,
            )
            await self.on_commit({"digest": dig, "leader": self.node_id})
        return {"ok": True}

    async def on_commit(self, body: dict) -> dict:
        dig = body["digest"]
        self.committed.setdefault(dig, set()).add(body.get("leader", "unknown"))
        self.committed[dig].add(self.node_id)
        if dig not in self.decided and len(self.committed[dig]) >= self.quorum():
            self.decided[dig] = {"digest": dig, "decided": True, "ts": time.time()}
            fut = self._pending.pop(dig, None)
            if fut and not fut.done():
                fut.set_result({"accepted": True, "digest": dig, "seq": self.seq, "decided": True})
        return {"ok": True}

    def quorum(self) -> int:
        n = len(self.peers) + 1
        f = (n - 1) // 3
        return max((n // 2) + 1, 2 * f + 1)


async def mount_pbft(app) -> None:
    r = APIRouter()
    s = get_settings()
    peers = [p for p in s.cluster_nodes if f":{s.http_port}" not in p]
    node = PbftNode(s.node_id, peers)

    @r.post("/pbft/request")
    async def pbft_request(body: dict = Body(...), principal=Depends(require_role("writer"))):
        return await node.pre_prepare(body)

    @r.post("/pbft/prepare")
    async def prepare(body: dict = Body(...)):
        return await node.on_prepare(body)

    @r.post("/pbft/commit")
    async def commit(body: dict = Body(...)):
        return await node.on_commit(body)

    @r.get("/pbft/status")
    async def status():
        return {
            "node": node.node_id,
            "view": node.view,
            "prepared": {k: len(v) for k, v in node.prepared.items()},
            "committed": {k: len(v) for k, v in node.committed.items()},
            "decided": list(node.decided.keys()),
            "quorum": node.quorum(),
        }

    app.include_router(r)
