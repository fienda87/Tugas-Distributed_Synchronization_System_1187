from prometheus_client import Counter, Histogram

REQS = Counter("http_requests_total", "Total HTTP requests", ["service", "path", "status"])
LAT = Histogram("http_request_latency_seconds", "HTTP latency", ["service", "path"])
RAFT_TERM = Counter("raft_term_changes_total", "Raft term changes")
RAFT_APPEND = Counter("raft_append_entries_total", "Raft append", ["result"])
QUEUE_PUB = Counter("queue_publish_total", "Queue publish", ["topic"])
QUEUE_ACK = Counter("queue_ack_total", "Queue ack", ["topic"])
CACHE_HIT = Counter("cache_hits_total", "Cache hits", ["node"])
CACHE_MISS = Counter("cache_miss_total", "Cache miss", ["node"])
