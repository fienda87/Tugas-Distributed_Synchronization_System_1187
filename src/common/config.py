from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache


def _split_csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


@dataclass
class Settings:
    role: str = os.getenv("ROLE", "lock")
    node_id: str = os.getenv("NODE_ID", "node-1")
    http_port: int = int(os.getenv("HTTP_PORT", "9000"))

    cluster_nodes: list[str] = field(default_factory=list)  # lock
    cluster_peers: list[str] = field(default_factory=list)  # queue/cache
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    raft_election_min_ms: int = int(os.getenv("RAFT_ELECTION_MIN_MS", "180"))
    raft_election_max_ms: int = int(os.getenv("RAFT_ELECTION_MAX_MS", "320"))
    raft_heartbeat_ms: int = int(os.getenv("RAFT_HEARTBEAT_MS", "80"))

    queue_replica_factor: int = int(os.getenv("QUEUE_REPLICA_FACTOR", "2"))
    queue_visibility_ms: int = int(os.getenv("QUEUE_VISIBILITY_MS", "25000"))

    cache_capacity: int = int(os.getenv("CACHE_CAPACITY", "512"))
    cache_default_ttl_ms: int = int(os.getenv("CACHE_DEFAULT_TTL_MS", "60000"))

    auth_enabled: bool = os.getenv("AUTH_ENABLED", "true").lower() == "true"
    api_keys: str = os.getenv("API_KEYS", "")
    internal_api_key: str = os.getenv("INTERNAL_API_KEY", "")
    audit_log_path: str = os.getenv("AUDIT_LOG_PATH", "/data/audit.log")
    audit_hash_path: str = os.getenv("AUDIT_HASH_PATH", "/data/audit.hash")

    inter_node_enc: bool = os.getenv("INTER_NODE_ENC", "true").lower() == "true"
    enc_shared_key_b64: str = os.getenv(
        "ENC_SHARED_KEY_BASE64",
        "2xQq0M0pB1jU1m8eY2QGhr0n6B7aB23ChzldnKmv3g0=",
    )

    region: str = os.getenv("REGION", "ap-south")
    region_map: str = os.getenv("REGION_MAP", "")

    balancer_sample_ms: int = int(os.getenv("BALANCER_SAMPLE_MS", "3000"))

    def __post_init__(self) -> None:
        # Dataclass fields default to empty; load env values here.
        self.cluster_nodes = _split_csv(os.getenv("CLUSTER_NODES", ""))
        self.cluster_peers = _split_csv(os.getenv("CLUSTER_PEERS", ""))


@lru_cache
def get_settings() -> Settings:
    return Settings()
