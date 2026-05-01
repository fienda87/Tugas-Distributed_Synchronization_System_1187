from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from typing import Any

from common.config import get_settings


@dataclass
class AuditEvent:
    ts: float
    actor: str
    action: str
    target: str
    data: dict[str, Any]


class AuditLog:
    def __init__(self) -> None:
        s = get_settings()
        self.log_path = s.audit_log_path
        self.hash_path = s.audit_hash_path
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        os.makedirs(os.path.dirname(self.hash_path), exist_ok=True)

    def _read_prev_hash(self) -> str:
        if not os.path.exists(self.hash_path):
            return "0" * 64
        with open(self.hash_path, "r", encoding="utf-8") as f:
            return f.read().strip() or ("0" * 64)

    def _write_hash(self, h: str) -> None:
        with open(self.hash_path, "w", encoding="utf-8") as f:
            f.write(h)

    def append(self, ev: AuditEvent) -> str:
        prev = self._read_prev_hash()
        record = {
            "ts": ev.ts,
            "actor": ev.actor,
            "action": ev.action,
            "target": ev.target,
            "data": ev.data,
            "prev": prev,
        }
        payload = json.dumps(record, separators=(",", ":"), sort_keys=True)
        h = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        record["hash"] = h

        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, separators=(",", ":")) + "\n")
        self._write_hash(h)
        return h


AUDIT = AuditLog()


def audit(actor: str, action: str, target: str, data: dict[str, Any]) -> str:
    ev = AuditEvent(ts=time.time(), actor=actor, action=action, target=target, data=data)
    return AUDIT.append(ev)
