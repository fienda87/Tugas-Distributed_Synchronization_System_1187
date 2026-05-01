from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict

from fastapi import APIRouter, Body, Query, Depends

from common.config import get_settings
from common.security import require_role


@dataclass
class NodeStat:
    ewma_ms: float = 0.0
    samples: int = 0
    last_ts: float = 0.0
    ok: int = 0
    err: int = 0

    def update(self, latency_ms: float, ok: bool) -> None:
        alpha = 0.2 if self.samples > 10 else 0.5
        self.ewma_ms = latency_ms if self.samples == 0 else (alpha * latency_ms + (1 - alpha) * self.ewma_ms)
        self.samples += 1
        self.last_ts = time.time()
        if ok:
            self.ok += 1
        else:
            self.err += 1

    def score(self) -> float:
        err_rate = (self.err / max(1, self.ok + self.err))
        return self.ewma_ms * (1.0 + err_rate * 2.0)


class Balancer:
    def __init__(self) -> None:
        self.stats: Dict[str, NodeStat] = {}

    def report(self, node: str, latency_ms: float, ok: bool) -> None:
        st = self.stats.setdefault(node, NodeStat())
        st.update(latency_ms, ok)

    def choose(self, nodes: list[str]) -> str:
        best = None
        best_score = None
        for n in nodes:
            st = self.stats.get(n)
            score = st.score() if st else 999999.0
            if best is None or score < best_score:
                best = n
                best_score = score
        return best or (nodes[0] if nodes else "")


async def mount_balancer(app) -> None:
    r = APIRouter()
    bal = Balancer()

    @r.post("/balancer/report")
    async def report(body: dict = Body(...), principal=Depends(require_role("writer"))):
        node = body.get("node")
        latency_ms = float(body.get("latency_ms", 0.0))
        ok = bool(body.get("ok", True))
        if node:
            bal.report(node, latency_ms, ok)
        return {"ok": True}

    @r.get("/balancer/next")
    async def next_node(nodes: str = Query(""), principal=Depends(require_role("reader"))):
        node_list = [n.strip() for n in nodes.split(",") if n.strip()]
        return {"node": bal.choose(node_list)}

    app.include_router(r)
