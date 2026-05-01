from __future__ import annotations

from fastapi import APIRouter, Query, Depends

from common.config import get_settings
from common.security import require_role


def _parse_region_map(raw: str) -> dict[str, int]:
    # format: region:latency_ms,region:latency_ms
    out: dict[str, int] = {}
    for item in [x.strip() for x in raw.split(",") if x.strip()]:
        if ":" not in item:
            continue
        name, val = item.split(":", 1)
        try:
            out[name.strip()] = int(val.strip())
        except Exception:
            continue
    return out


def choose_region(client_region: str, regions: dict[str, int]) -> str:
    if client_region in regions:
        return min(regions.keys(), key=lambda r: regions[r])
    return min(regions.keys(), key=lambda r: regions[r]) if regions else client_region


async def mount_geo(app) -> None:
    r = APIRouter()
    s = get_settings()

    @r.get("/geo/route")
    async def geo_route(client_region: str = Query(...), principal=Depends(require_role("reader"))):
        regions = _parse_region_map(s.region_map)
        if not regions:
            return {"region": s.region, "latency_ms": 0}
        best = choose_region(client_region, regions)
        return {"region": best, "latency_ms": regions.get(best, 0), "known": regions}

    app.include_router(r)
