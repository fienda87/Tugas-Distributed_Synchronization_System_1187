from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from fastapi import APIRouter, Body, HTTPException, Depends

from common.audit import audit
from common.security import require_role
from common.config import get_settings
from consensus.raft import RaftCore
from transport.http import HTTP


class LockTable:
    def __init__(self) -> None:
        self.state: Dict[str, dict] = {}
        self.waits: Dict[str, Set[str]] = {}
        self._counter = 0

    def _new_token(self) -> str:
        self._counter += 1
        return f"lk{self._counter}"

    def _holders(self, resource: str) -> Set[str]:
        ent = self.state.get(resource, {})
        return {c for c, _ in ent.get("holders", set())}

    def _add_wait(self, waiter: str, holders: Set[str]) -> None:
        self.waits.setdefault(waiter, set()).update(holders)

    def _clear_wait(self, client_id: str) -> None:
        self.waits.pop(client_id, None)

    def apply(self, cmd: dict) -> dict:
        op = cmd.get("op")
        if op == "acquire":
            res = cmd["resource"]
            mode = cmd["mode"]
            client = cmd["client_id"]
            ent = self.state.setdefault(res, {"mode": None, "holders": set(), "queue": []})

            if not ent["holders"]:
                tok = self._new_token()
                ent["mode"] = mode
                ent["holders"].add((client, tok))
                return {"granted": True, "token": tok, "resource": res, "mode": mode}

            if ent["mode"] == "shared" and mode == "shared":
                tok = self._new_token()
                ent["holders"].add((client, tok))
                return {"granted": True, "token": tok, "resource": res, "mode": "shared"}

            ent["queue"].append({"client": client, "mode": mode})
            self._add_wait(client, self._holders(res))
            return {"granted": False, "queued": True, "resource": res, "mode": mode}

        if op == "release":
            res = cmd["resource"]
            token = cmd["token"]
            ent = self.state.get(res)
            if not ent:
                return {"released": False, "reason": "missing"}

            before = set(ent["holders"])
            ent["holders"] = {(c, t) for (c, t) in ent["holders"] if t != token}
            changed = before != ent["holders"]
            if ent["holders"]:
                return {"released": bool(changed), "resource": res}

            ent["mode"] = None
            if not ent["queue"]:
                return {"released": bool(changed), "resource": res}

            head = ent["queue"][0]
            if head["mode"] == "shared":
                ent["mode"] = "shared"
                batch = []
                while ent["queue"] and ent["queue"][0]["mode"] == "shared":
                    req = ent["queue"].pop(0)
                    tok = self._new_token()
                    ent["holders"].add((req["client"], tok))
                    self._clear_wait(req["client"])
                    batch.append({"client": req["client"], "token": tok})
                return {"released": bool(changed), "granted_batch": batch, "resource": res, "mode": "shared"}

            req = ent["queue"].pop(0)
            ent["mode"] = "exclusive"
            tok = self._new_token()
            ent["holders"].add((req["client"], tok))
            self._clear_wait(req["client"])
            return {"released": bool(changed), "granted": {"client": req["client"], "token": tok}, "resource": res}

        if op == "deadlock_check":
            visited: Set[str] = set()
            stack: Set[str] = set()

            def dfs(u: str) -> bool:
                visited.add(u)
                stack.add(u)
                for v in self.waits.get(u, set()):
                    if v not in visited and dfs(v):
                        return True
                    if v in stack:
                        return True
                stack.remove(u)
                return False

            dead = any(dfs(u) for u in list(self.waits.keys()) if u not in visited)
            return {"deadlock": bool(dead)}

        return {"ok": True}


@dataclass
class Pending:
    fut: asyncio.Future


class LockRsm:
    def __init__(self) -> None:
        self.table = LockTable()
        self.raft: Optional[RaftCore] = None
        self._pending: Dict[str, Pending] = {}

    async def apply_cmd(self, cmd: dict) -> dict:
        res = self.table.apply(cmd)
        req_id = cmd.get("req_id")
        if req_id and req_id in self._pending:
            p = self._pending.pop(req_id)
            if not p.fut.done():
                p.fut.set_result(res)
        return res

    def _register(self, req_id: str) -> asyncio.Future:
        fut = asyncio.get_running_loop().create_future()
        self._pending[req_id] = Pending(fut=fut)
        return fut


async def _find_leader(cluster: list[str]) -> Optional[str]:
    for url in cluster:
        try:
            j = await HTTP.get_json(f"{url}/raft/role", timeout=1.0)
            if j.get("role") == "leader":
                return url
        except Exception:
            continue
    return None


async def mount_lock(app) -> LockRsm:
    r = APIRouter()
    s = get_settings()
    rsm = LockRsm()

    peers = [p for p in s.cluster_nodes if f":{s.http_port}" not in p]
    rsm.raft = RaftCore(s.node_id, peers, rsm.apply_cmd)
    await rsm.raft.start()

    @r.post("/lock/acquire")
    async def acquire(body: dict = Body(...), principal=Depends(require_role("writer"))):
        if rsm.raft.role != "leader":
            leader = await _find_leader(s.cluster_nodes)
            if not leader:
                raise HTTPException(503, "no_leader")
            return await HTTP.post_json(f"{leader}/lock/acquire", body, timeout=2.5)

        req_id = body.get("req_id") or str(uuid.uuid4())
        cmd = dict(body, op="acquire", req_id=req_id)
        fut = rsm._register(req_id)
        ok = await rsm.raft.submit(cmd)
        if not ok:
            raise HTTPException(503, "replication_failed")
        try:
            res = await asyncio.wait_for(fut, timeout=2.0)
        except asyncio.TimeoutError:
            res = {"accepted": True, "pending": True}
        audit(principal.api_key, "lock_acquire", body.get("resource", ""), {"mode": body.get("mode")})
        return res

    @r.post("/lock/release")
    async def release(body: dict = Body(...), principal=Depends(require_role("writer"))):
        if rsm.raft.role != "leader":
            leader = await _find_leader(s.cluster_nodes)
            if not leader:
                raise HTTPException(503, "no_leader")
            return await HTTP.post_json(f"{leader}/lock/release", body, timeout=2.5)

        req_id = str(uuid.uuid4())
        cmd = dict(body, op="release", req_id=req_id)
        fut = rsm._register(req_id)
        ok = await rsm.raft.submit(cmd)
        if not ok:
            raise HTTPException(503, "replication_failed")
        try:
            res = await asyncio.wait_for(fut, timeout=2.0)
        except asyncio.TimeoutError:
            res = {"accepted": True, "pending": True}
        audit(principal.api_key, "lock_release", body.get("resource", ""), {})
        return res

    @r.post("/lock/deadlock")
    async def deadlock(principal=Depends(require_role("reader"))):
        if rsm.raft.role != "leader":
            leader = await _find_leader(s.cluster_nodes)
            if not leader:
                raise HTTPException(503, "no_leader")
            return await HTTP.post_json(f"{leader}/lock/deadlock", {}, timeout=2.5)

        req_id = str(uuid.uuid4())
        cmd = {"op": "deadlock_check", "req_id": req_id}
        fut = rsm._register(req_id)
        ok = await rsm.raft.submit(cmd)
        if not ok:
            raise HTTPException(503, "replication_failed")
        try:
            return await asyncio.wait_for(fut, timeout=2.0)
        except asyncio.TimeoutError:
            return {"accepted": True, "pending": True}

    @r.get("/lock/state")
    async def state(resource: Optional[str] = None, principal=Depends(require_role("reader"))):
        tab = rsm.table.state
        def fmt(ent: dict) -> dict:
            return {
                "mode": ent.get("mode"),
                "holders": [{"client": c, "token": t} for c, t in ent.get("holders", set())],
                "queue": list(ent.get("queue", [])),
            }
        if resource:
            ent = tab.get(resource)
            return {resource: fmt(ent)} if ent else {}
        return {k: fmt(v) for k, v in tab.items()}

    @r.post("/raft/request_vote")
    async def request_vote(body: dict = Body(...)):
        return await rsm.raft.handle_request_vote(**body)

    @r.post("/raft/append_entries")
    async def append_entries(body: dict = Body(...)):
        return await rsm.raft.handle_append_entries(**body)

    @r.get("/raft/role")
    async def role():
        return {"role": rsm.raft.role, "leader": rsm.raft.leader_id}

    app.include_router(r)
    return rsm
