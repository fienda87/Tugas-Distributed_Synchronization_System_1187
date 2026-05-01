import os
import random
import uuid
from locust import HttpUser, task, between, tag

QUEUE_HOST = os.getenv("QUEUE_HOST", "http://localhost:9102")
CACHE_HOST = os.getenv("CACHE_HOST", "http://localhost:9200")
LOCK_HOST = os.getenv("LOCK_HOST", "http://localhost:9000")
API_KEY = os.getenv("API_KEY", "demo_writer")

QUEUE_TOPIC = os.getenv("QUEUE_TOPIC", "bench_v2")
QUEUE_KEY = os.getenv("QUEUE_KEY", "user_v2")
QUEUE_VIS_TTL = int(os.getenv("QUEUE_VIS_TTL_MS", "3000"))

CACHE_PCT_GET = int(os.getenv("LOCUST_CACHE_GET", "80"))
CACHE_MAX_KEYS = int(os.getenv("LOCUST_CACHE_KEYS", "2000"))
LOCK_RES_COUNT = int(os.getenv("LOCUST_LOCK_RES", "10"))

QUEUE_WEIGHT = int(os.getenv("QUEUE_WEIGHT", "3"))
CACHE_WEIGHT = int(os.getenv("CACHE_WEIGHT", "2"))
LOCK_WEIGHT = int(os.getenv("LOCK_WEIGHT", "1"))

COMMON_HEADERS = {"X-API-Key": API_KEY}


class QueueUser(HttpUser):
    host = QUEUE_HOST
    weight = max(0, QUEUE_WEIGHT)
    wait_time = between(0.01, 0.05)

    @tag("queue")
    @task(3)
    def publish(self):
        self.client.post(
            "/queue/publish",
            params={"topic": QUEUE_TOPIC, "key": QUEUE_KEY},
            json={"n": random.randint(1, 1_000_000)},
            headers=COMMON_HEADERS,
            name="queue:publish",
        )

    @tag("queue")
    @task(1)
    def consume_ack(self):
        r = self.client.post(
            "/queue/consume",
            params={"topic": QUEUE_TOPIC, "key": QUEUE_KEY, "visibility_ttl": QUEUE_VIS_TTL, "max": 10},
            headers=COMMON_HEADERS,
            name="queue:consume",
        )
        if r.status_code != 200:
            return
        items = r.json() or []
        for it in items:
            self.client.post(
                "/queue/ack_owner",
                params={"topic": QUEUE_TOPIC, "owner": it.get("owner"), "msg_id": it.get("msg_id")},
                headers=COMMON_HEADERS,
                name="queue:ack_owner",
            )


class CacheUser(HttpUser):
    host = CACHE_HOST
    weight = max(0, CACHE_WEIGHT)
    wait_time = between(0.01, 0.05)

    @tag("cache")
    @task
    def work(self):
        key = f"k{random.randint(1, CACHE_MAX_KEYS)}"
        if random.randint(1, 100) <= CACHE_PCT_GET:
            self.client.get("/cache/get", params={"key": key}, headers=COMMON_HEADERS, name="cache:get")
        else:
            self.client.post("/cache/put", json={"key": key, "value": random.randint(1, 1_000_000)}, headers=COMMON_HEADERS, name="cache:put")


class LockUser(HttpUser):
    host = LOCK_HOST
    weight = max(0, LOCK_WEIGHT)
    wait_time = between(0.01, 0.03)
    resources = [f"res_{i}" for i in range(LOCK_RES_COUNT)]

    def on_start(self):
        self.client_id = f"locust-{uuid.uuid4().hex[:8]}"

    @tag("lock")
    @task
    def exclusive_cycle(self):
        res = random.choice(self.resources)
        r = self.client.post(
            "/lock/acquire",
            json={"resource": res, "mode": "exclusive", "client_id": self.client_id, "timeout_ms": 2000},
            headers=COMMON_HEADERS,
            name="lock:acquire",
        )
        if r.status_code == 200 and (r.json() or {}).get("granted"):
            tok = r.json().get("token")
            self.client.post(
                "/lock/release",
                json={"resource": res, "token": tok},
                headers=COMMON_HEADERS,
                name="lock:release",
            )
