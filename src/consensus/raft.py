from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from common.config import get_settings
from common.metrics import RAFT_APPEND, RAFT_TERM
from transport.http import HTTP


@dataclass
class LogEntry:
    term: int
    cmd: dict


class RaftCore:
    def __init__(self, node_id: str, peers: list[str], apply_fn: Callable[[dict], "asyncio.Future"]):
        self.node_id = node_id
        self.peers = peers
        self.apply_fn = apply_fn

        self.term = 0
        self.voted_for: Optional[str] = None
        self.log: list[LogEntry] = []
        self.commit_index = 0
        self.last_applied = 0

        self.role = "follower"
        self.leader_id: Optional[str] = None

        self._election_deadline = 0.0
        self._stop = False
        self._election_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._reset_election_timer()

    def _reset_election_timer(self) -> None:
        s = get_settings()
        self._election_deadline = time.monotonic() + random.uniform(
            s.raft_election_min_ms / 1000.0, s.raft_election_max_ms / 1000.0
        )

    async def start(self) -> None:
        self._election_task = asyncio.create_task(self._election_loop())

    async def stop(self) -> None:
        self._stop = True
        for task in [self._election_task, self._heartbeat_task]:
            if task:
                task.cancel()

    async def _election_loop(self) -> None:
        while not self._stop:
            await asyncio.sleep(0.02)
            if self.role == "leader":
                continue
            if time.monotonic() < self._election_deadline:
                continue

            self.role = "candidate"
            self.term += 1
            RAFT_TERM.inc()
            self.voted_for = self.node_id
            votes = 1
            self._reset_election_timer()

            last_idx = len(self.log)
            last_term = self.log[-1].term if self.log else 0

            for peer in self.peers:
                try:
                    resp = await HTTP.post_json(
                        f"{peer}/raft/request_vote",
                        {
                            "term": self.term,
                            "candidate_id": self.node_id,
                            "last_log_index": last_idx,
                            "last_log_term": last_term,
                        },
                        timeout=1.2,
                    )
                    if resp.get("vote_granted"):
                        votes += 1
                except Exception:
                    continue

            if votes > (len(self.peers) + 1) // 2:
                self.role = "leader"
                self.leader_id = self.node_id
                if self._heartbeat_task:
                    self._heartbeat_task.cancel()
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _heartbeat_loop(self) -> None:
        s = get_settings()
        while not self._stop and self.role == "leader":
            await self._broadcast_append(entries=[])
            await asyncio.sleep(s.raft_heartbeat_ms / 1000.0)

    async def _broadcast_append(self, entries: list[dict]) -> int:
        acks = 1
        prev_idx = len(self.log) - len(entries)
        prev_term = self.log[prev_idx - 1].term if prev_idx > 0 else 0
        for peer in self.peers:
            try:
                resp = await HTTP.post_json(
                    f"{peer}/raft/append_entries",
                    {
                        "term": self.term,
                        "leader_id": self.node_id,
                        "prev_log_index": prev_idx,
                        "prev_log_term": prev_term,
                        "entries": entries,
                        "leader_commit": self.commit_index,
                    },
                    timeout=1.6,
                )
                if resp.get("success"):
                    acks += 1
                    RAFT_APPEND.labels(result="ok").inc()
                else:
                    RAFT_APPEND.labels(result="fail").inc()
            except Exception:
                RAFT_APPEND.labels(result="fail").inc()
        return acks

    async def submit(self, cmd: dict) -> bool:
        if self.role != "leader":
            return False
        self.log.append(LogEntry(self.term, cmd))
        entry = {"term": self.term, "cmd": cmd}
        acks = await self._broadcast_append(entries=[entry])
        if acks > (len(self.peers) + 1) // 2:
            self.commit_index = len(self.log)
            await self._apply_commits()
            return True
        return False

    async def _apply_commits(self) -> None:
        while self.last_applied < self.commit_index:
            self.last_applied += 1
            cmd = self.log[self.last_applied - 1].cmd
            await self.apply_fn(cmd)

    async def handle_request_vote(
        self, term: int, candidate_id: str, last_log_index: int, last_log_term: int
    ) -> dict:
        if term > self.term:
            self.term = term
            self.role = "follower"
            self.voted_for = None

        local_last_term = self.log[-1].term if self.log else 0
        local_last_index = len(self.log)
        up_to_date = (last_log_term > local_last_term) or (
            last_log_term == local_last_term and last_log_index >= local_last_index
        )

        vote_granted = False
        if term >= self.term and up_to_date and self.voted_for in (None, candidate_id):
            self.voted_for = candidate_id
            vote_granted = True
            self._reset_election_timer()

        return {"term": self.term, "vote_granted": vote_granted}

    async def handle_append_entries(
        self,
        term: int,
        leader_id: str,
        prev_log_index: int,
        prev_log_term: int,
        entries: list[dict],
        leader_commit: int,
    ) -> dict:
        if term < self.term:
            return {"term": self.term, "success": False}

        self.term = term
        self.role = "follower"
        self.leader_id = leader_id
        self._reset_election_timer()

        if prev_log_index > 0:
            if len(self.log) < prev_log_index:
                return {"term": self.term, "success": False}
            if self.log[prev_log_index - 1].term != prev_log_term:
                return {"term": self.term, "success": False}

        for e in entries:
            self.log.append(LogEntry(e["term"], e["cmd"]))

        if leader_commit > self.commit_index:
            self.commit_index = min(leader_commit, len(self.log))
            await self._apply_commits()

        return {"term": self.term, "success": True}
