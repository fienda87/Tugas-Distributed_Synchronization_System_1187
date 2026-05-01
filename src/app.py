from __future__ import annotations

import asyncio
import socket
import time
import logging

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from common.config import get_settings
from common.metrics import REQS, LAT
from common.crypto import CryptoBox
from lock.lock_service import mount_lock
from dist_queue.queue_service import mount_queue
from cache.cache_service import mount_cache
from consensus.pbft import mount_pbft
from geo.router import mount_geo
from ml.balancer import mount_balancer


LOG_LEVEL = "INFO"
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("tugasDistribusi")

app = FastAPI(title="Distributed Sync v2", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

settings = get_settings()
_ready = False
_crypto = CryptoBox.from_env() if settings.inter_node_enc else None


@app.on_event("startup")
async def on_startup() -> None:
    global _ready
    logger.info("Boot role=%s id=%s port=%s", settings.role, settings.node_id, settings.http_port)
    if settings.role == "lock":
        await mount_lock(app)
    elif settings.role == "queue":
        await mount_queue(app)
    elif settings.role == "cache":
        await mount_cache(app)
    elif settings.role == "pbft":
        await mount_pbft(app)
    elif settings.role == "gateway":
        await mount_geo(app)
        await mount_balancer(app)
    else:
        logger.warning("Unknown ROLE=%s", settings.role)
    _ready = True


@app.get("/health")
async def health() -> dict:
    REQS.labels(service=settings.role, path="/health", status="200").inc()
    return {
        "status": "ok",
        "role": settings.role,
        "node_id": settings.node_id,
        "hostname": socket.gethostname(),
        "time": time.time(),
    }


@app.get("/readyz")
async def readyz() -> dict:
    REQS.labels(service=settings.role, path="/readyz", status="200").inc()
    return {"ready": bool(_ready)}


@app.get("/metrics")
async def metrics() -> Response:
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


@app.middleware("http")
async def _metrics_mw(request, call_next):
    start = time.perf_counter()
    try:
        if _crypto and request.headers.get("X-ENC") == "aesgcm":
            body = await request.body()
            if body:
                try:
                    decrypted = _crypto.decrypt(body)
                    request._body = decrypted  # type: ignore[attr-defined]
                except Exception:
                    pass
        resp = await call_next(request)
        status = str(resp.status_code)
    except Exception:
        status = "500"
        raise
    finally:
        try:
            dur = time.perf_counter() - start
            REQS.labels(service=settings.role, path=request.url.path, status=status).inc()
            LAT.labels(service=settings.role, path=request.url.path).observe(dur)
        except Exception:
            pass
    return resp
