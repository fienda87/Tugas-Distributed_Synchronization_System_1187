from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from typing import List, Optional

from fastapi import APIRouter, Body, HTTPException, Query, Depends
import redis.asyncio as redis

from common.audit import audit
from common.config import get_settings
from common.security import require_role
from common.metrics import QUEUE_PUB, QUEUE_ACK
from transport.http import HTTP


def _sha1_int(value: str) -> int:
    return int(hashlib.sha1(value.encode("utf-8")).hexdigest(), 16)


class Ring:
    def __init__(self, peers: List[str], vnodes: int = 64):
        self.points: List[tuple[int, str]] = []
        for p in peers:
            for v in range(vnodes):
                self.points.append((_sha1_int(f"{p}|{v}"), p))
        self.points.sort(key=lambda x: x[0])

    def owners(self, topic: str, key: Optional[str], r: int) -> List[str]:
        if r <= 0:
            r = 1
        h = _sha1_int(f"{topic}|{key or topic}")
        lo, hi = 0, len(self.points) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            if self.points[mid][0] < h:
                lo = mid + 1
            else:
                hi = mid - 1
        idx = lo if lo < len(self.points) else 0
        out, seen = [], set()
        i = idx
        while len(out) < min(r, len(self.points)):
            _, peer = self.points[i]
            if peer not in seen:
                out.append(peer)
                seen.add(peer)
            i = (i + 1) % len(self.points)
            if i == idx:
                break
        return out


@dataclass
class QueueKeys:
    topic: str
    owner: str

    @property
    def ready(self) -> str:
        return f"q2:{self.topic}:{self.owner}:ready"

    @property
    def inflight(self) -> str:
        return f"q2:{self.topic}:{self.owner}:inflight"


class QueueStore:
    def __init__(self, r: redis.Redis):
        self.r = r

    async def publish(self, topic: str, owner: str, msg_id: str, payload: dict) -> None:
        await self.r.hset(f"q2:msg:{msg_id}", mapping={"payload": json.dumps(payload), "topic": topic})
        await self.r.sadd(f"q2:owners:{msg_id}", owner)
        score = await self.r.incr("q2:seq")
        keys = QueueKeys(topic, owner)
        await self.r.zadd(keys.ready, {msg_id: float(score)})

    async def consume(self, topic: str, owner: str, max_n: int, ttl_ms: int) -> List[dict]:
        keys = QueueKeys(topic, owner)
        now = int(time.time() * 1000)
        out = []
        for _ in range(max_n):
            items = await self.r.zpopmin(keys.ready, count=1)
            if not items:
                break
            msg_id, _score = items[0]
            deadline = now + ttl_ms
            await self.r.zadd(keys.inflight, {msg_id: float(deadline)})
            raw = await self.r.hget(f"q2:msg:{msg_id}", "payload")
            payload = json.loads(raw) if raw else None
            out.append({"msg_id": msg_id, "payload": payload, "owner": owner})
        return out

    async def ack_owner(self, topic: str, owner: str, msg_id: str) -> bool:
        keys = QueueKeys(topic, owner)
        removed = await self.r.zrem(keys.inflight, msg_id)
        await self.r.zrem(keys.ready, msg_id)
        if removed:
            await self.r.srem(f"q2:owners:{msg_id}", owner)
            if await self.r.scard(f"q2:owners:{msg_id}") == 0:
                await self.r.delete(f"q2:msg:{msg_id}")
                await self.r.delete(f"q2:owners:{msg_id}")
        return bool(removed)

    async def ack_any(self, topic: str, msg_id: str) -> bool:
        owners = await self.r.smembers(f"q2:owners:{msg_id}")
        removed_any = False
        for owner in owners:
            removed_any = await self.ack_owner(topic, owner, msg_id) or removed_any
        return removed_any

    async def requeue_expired(self, topic: str, owner: str) -> int:
        keys = QueueKeys(topic, owner)
        now = int(time.time() * 1000)
        expired = await self.r.zrangebyscore(keys.inflight, min=0, max=now)
        if not expired:
            return 0
        count = 0
        for msg_id in expired:
            await self.r.zrem(keys.inflight, msg_id)
            score = await self.r.incr("q2:seq")
            await self.r.zadd(keys.ready, {msg_id: float(score)})
            count += 1
        return count


async def mount_queue(app) -> None:
    r = APIRouter()
    s = get_settings()
    rds = redis.from_url(s.redis_url, decode_responses=True)
    store = QueueStore(rds)

    peers = list(s.cluster_peers or [])
    self_url = f"http://{s.node_id}:{s.http_port}"
    if self_url not in peers:
        peers.append(self_url)
    ring = Ring(peers, vnodes=64)

    async def reaper() -> None:
        await asyncio.sleep(1.0)
        while True:
            try:
                topics = await rds.smembers("q2:topics")
                for t in topics:
                    await store.requeue_expired(t, self_url)
            except Exception:
                pass
            await asyncio.sleep(0.5)

    app.add_event_handler("startup", lambda: asyncio.create_task(reaper()))

    @r.get("/readyz")
    async def readyz():
        try:
            await rds.ping()
            return {"ready": True}
        except Exception:
            return {"ready": False}

    @r.get("/queue/owners")
    async def owners(topic: str, key: Optional[str] = None, principal=Depends(require_role("reader"))):
        return {"owners": ring.owners(topic, key, s.queue_replica_factor), "self": self_url}

    @r.post("/queue/publish")
    async def publish(topic: str, key: Optional[str] = None, payload: dict = Body(...), principal=Depends(require_role("writer"))):
        await rds.sadd("q2:topics", topic)
        msg_id = uuid.uuid4().hex
        owners = ring.owners(topic, key, s.queue_replica_factor)
        for ow in owners:
            if ow == self_url:
                await store.publish(topic, ow, msg_id, payload)
            else:
                await HTTP.post_json(
                    f"{ow}/queue/publish_internal",
                    {"topic": topic, "owner": ow, "msg_id": msg_id, "payload": payload},
                    timeout=2.0,
                )
        QUEUE_PUB.labels(topic=topic).inc()
        audit(principal.api_key, "queue_publish", topic, {"msg_id": msg_id})
        return {"msg_id": msg_id, "owners": owners}

    @r.post("/queue/publish_internal")
    async def publish_internal(body: dict = Body(...)):
        if body.get("owner") != self_url:
            raise HTTPException(403, "wrong_owner")
        await rds.sadd("q2:topics", body["topic"])
        await store.publish(body["topic"], body["owner"], body["msg_id"], body["payload"])
        return {"ok": True}

    @r.post("/queue/consume")
    async def consume(
        topic: str = Query(...),
        key: Optional[str] = None,
        visibility_ttl: Optional[int] = None,
        max: int = 1,
        principal=Depends(require_role("reader")),
    ):
        ttl_ms = int(visibility_ttl or s.queue_visibility_ms)
        owners = ring.owners(topic, key, s.queue_replica_factor)
        for ow in owners:
            try:
                if ow == self_url:
                    items = await store.consume(topic, ow, max, ttl_ms)
                else:
                    items = await HTTP.get_json(
                        f"{ow}/queue/consume_internal?topic={topic}&owner={ow}&visibility_ttl={ttl_ms}&max={max}",
                        timeout=2.0,
                    )
                if items:
                    return items
            except Exception:
                continue
        return []

    @r.get("/queue/consume_internal")
    async def consume_internal(topic: str, owner: str, visibility_ttl: int, max: int = 1):
        if owner != self_url:
            raise HTTPException(403, "wrong_owner")
        return await store.consume(topic, owner, max, visibility_ttl)

    @r.post("/queue/ack_owner")
    async def ack_owner(topic: str, owner: str, msg_id: str, principal=Depends(require_role("writer"))):
        ok = await store.ack_any(topic, msg_id)
        if ok:
            QUEUE_ACK.labels(topic=topic).inc()
        return {"acked": bool(ok)}

    @r.post("/queue/ack_owner_internal")
    async def ack_owner_internal(body: dict = Body(...)):
        if body.get("owner") != self_url:
            raise HTTPException(403, "wrong_owner")
        ok = await store.ack_owner(body["topic"], body["owner"], body["msg_id"])
        if ok:
            QUEUE_ACK.labels(topic=body["topic"]).inc()
        return {"acked": bool(ok)}

    @r.post("/queue/ack")
    async def ack(topic: str, msg_id: str, principal=Depends(require_role("writer"))):
        ok = await store.ack_any(topic, msg_id)
        if ok:
            QUEUE_ACK.labels(topic=topic).inc()
        return {"acked": bool(ok)}

    app.include_router(r)
