from __future__ import annotations

import asyncio
import json
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Optional

from fastapi import APIRouter, Body, Query, Depends
import redis.asyncio as redis

from common.config import get_settings
from common.metrics import CACHE_HIT, CACHE_MISS
from common.security import require_role
from common.audit import audit


MESI_I = "I"
MESI_S = "S"
MESI_E = "E"
MESI_M = "M"


@dataclass
class Entry:
    value: Any
    state: str
    expire_at_ms: Optional[int] = None


class LruCache:
    def __init__(self, capacity: int):
        self.capacity = max(1, capacity)
        self.data: OrderedDict[str, Entry] = OrderedDict()
        self.evictions = 0

    def _expired(self, e: Entry) -> bool:
        return e.expire_at_ms is not None and e.expire_at_ms <= int(time.time() * 1000)

    def get(self, key: str) -> Optional[Entry]:
        e = self.data.get(key)
        if e is None:
            return None
        if e.state == MESI_I or self._expired(e):
            self.data.pop(key, None)
            return None
        self.data.move_to_end(key, last=True)
        return e

    def put(self, key: str, entry: Entry) -> None:
        if key in self.data:
            self.data.pop(key)
        elif len(self.data) >= self.capacity:
            self.data.popitem(last=False)
            self.evictions += 1
        self.data[key] = entry

    def invalidate(self, key: str) -> None:
        if key in self.data:
            self.data.pop(key, None)

    def state_of(self, key: str) -> Optional[str]:
        e = self.data.get(key)
        return e.state if e else None


class CacheNode:
    def __init__(self, r: redis.Redis, capacity: int, self_url: str):
        self.r = r
        self.cache = LruCache(capacity)
        self.self_url = self_url
        self.metrics = {"hits": 0, "misses": 0, "puts": 0, "evictions": 0, "inv_sent": 0, "inv_recv": 0}

    async def write_through(self, key: str, value: Any, ttl_ms: Optional[int]) -> None:
        encoded = json.dumps(value, separators=(",", ":"))
        if ttl_ms and ttl_ms > 0:
            await self.r.psetex(f"c2:data:{key}", ttl_ms, encoded)
            expire_at = int(time.time() * 1000) + ttl_ms
        else:
            await self.r.set(f"c2:data:{key}", encoded)
            expire_at = None
        self.cache.put(key, Entry(value=value, state=MESI_M, expire_at_ms=expire_at))
        self.metrics["puts"] += 1
        self.metrics["evictions"] = self.cache.evictions

    async def read_through(self, key: str) -> tuple[bool, Optional[Any]]:
        e = self.cache.get(key)
        if e:
            self.metrics["hits"] += 1
            CACHE_HIT.labels(node=self.self_url).inc()
            return True, e.value

        raw = await self.r.get(f"c2:data:{key}")
        if raw is None:
            self.metrics["misses"] += 1
            CACHE_MISS.labels(node=self.self_url).inc()
            return False, None
        try:
            val = json.loads(raw)
        except Exception:
            val = raw

        ttl_ms = await self.r.pttl(f"c2:data:{key}")
        expire_at = int(time.time() * 1000) + ttl_ms if ttl_ms and ttl_ms > 0 else None
        self.cache.put(key, Entry(value=val, state=MESI_S, expire_at_ms=expire_at))
        self.metrics["misses"] += 1
        CACHE_MISS.labels(node=self.self_url).inc()
        return True, val

    async def broadcast_inv(self, key: str) -> None:
        payload = {"op": "inv", "key": key, "from": self.self_url, "ts": int(time.time() * 1000)}
        await self.r.publish("c2:inv", json.dumps(payload))
        self.metrics["inv_sent"] += 1

    def apply_inv(self, key: str) -> None:
        self.cache.invalidate(key)
        self.metrics["inv_recv"] += 1


async def mount_cache(app) -> None:
    r = APIRouter()
    s = get_settings()
    rds = redis.from_url(s.redis_url, decode_responses=True)
    self_url = f"http://{s.node_id}:{s.http_port}"
    node = CacheNode(rds, capacity=s.cache_capacity, self_url=self_url)

    async def inv_listener() -> None:
        await asyncio.sleep(0.2)
        pub = rds.pubsub()
        await pub.subscribe("c2:inv")
        try:
            while True:
                msg = await pub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if msg and isinstance(msg.get("data"), str):
                    try:
                        data = json.loads(msg["data"])
                        if data.get("op") == "inv" and data.get("from") != self_url:
                            node.apply_inv(data.get("key"))
                    except Exception:
                        pass
                await asyncio.sleep(0.05)
        finally:
            await pub.unsubscribe("c2:inv")
            await pub.close()

    app.add_event_handler("startup", lambda: asyncio.create_task(inv_listener()))

    @r.get("/readyz")
    async def readyz():
        try:
            await rds.ping()
            return {"ready": True}
        except Exception:
            return {"ready": False}

    @r.post("/cache/put")
    async def cache_put(body: dict = Body(...), ttl_ms: Optional[int] = Query(None), principal=Depends(require_role("writer"))):
        key = body.get("key")
        value = body.get("value")
        if not isinstance(key, str):
            return {"stored": False, "error": "key_required"}
        await node.write_through(key, value, ttl_ms)
        await node.broadcast_inv(key)
        audit(principal.api_key, "cache_put", key, {"ttl_ms": ttl_ms})
        return {"stored": True}

    @r.get("/cache/get")
    async def cache_get(key: str, principal=Depends(require_role("reader"))):
        hit, val = await node.read_through(key)
        if not hit:
            return {"hit": False}
        return {"hit": True, "value": val}

    @r.get("/cache/state")
    async def cache_state(key: str, principal=Depends(require_role("reader"))):
        return {"key": key, "state": node.cache.state_of(key)}

    @r.get("/cache/metrics")
    async def cache_metrics(principal=Depends(require_role("reader"))):
        return {"node": self_url, "metrics": node.metrics, "evictions": node.cache.evictions}

    app.include_router(r)
