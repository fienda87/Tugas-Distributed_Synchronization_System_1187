from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Optional

from fastapi import Header, HTTPException, status, Depends

from common.config import get_settings


@dataclass
class ApiPrincipal:
    api_key: str
    role: str


def _parse_api_keys(raw: str) -> dict[str, str]:
    # format: key:role,key:role
    out: dict[str, str] = {}
    for item in [x.strip() for x in raw.split(",") if x.strip()]:
        if ":" not in item:
            continue
        key, role = item.split(":", 1)
        out[key.strip()] = role.strip()
    return out


def _role_allowed(role: str, required: str) -> bool:
    hierarchy = {"admin": 3, "writer": 2, "reader": 1}
    return hierarchy.get(role, 0) >= hierarchy.get(required, 0)


def require_role(required: str):
    async def _dep(x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")) -> ApiPrincipal:
        s = get_settings()
        if not s.auth_enabled:
            return ApiPrincipal(api_key="disabled", role="admin")
        if not x_api_key:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing_api_key")
        keys = _parse_api_keys(s.api_keys)
        role = keys.get(x_api_key)
        if not role:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid_api_key")
        if not _role_allowed(role, required):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient_role")
        return ApiPrincipal(api_key=x_api_key, role=role)

    return _dep
