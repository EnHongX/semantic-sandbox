"""Shared API key authentication for REST endpoints."""
from __future__ import annotations

import hmac
import os
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

_TRUTHY = {"1", "true", "yes", "on"}
_PUBLIC_GET_PATHS = {"/api/count", "/api/model/status"}
_PUBLIC_GET_PREFIXES = ("/api/samples/",)


def auth_enabled() -> bool:
    return os.environ.get("AUTH_ENABLED", "0").strip().lower() in _TRUTHY


def api_key_header_name() -> str:
    return os.environ.get("API_KEY_HEADER", "X-API-Key").strip() or "X-API-Key"


def configured_api_key() -> str:
    return os.environ.get("API_KEY", "").strip()


def _is_public_api_request(request: Request) -> bool:
    if request.method != "GET":
        return False
    path = request.url.path
    return path in _PUBLIC_GET_PATHS or any(path.startswith(prefix) for prefix in _PUBLIC_GET_PREFIXES)


def install_api_key_auth(app: FastAPI) -> None:
    @app.middleware("http")
    async def api_key_auth(request: Request, call_next: Callable[[Request], Awaitable]):
        if not auth_enabled() or not request.url.path.startswith("/api/") or _is_public_api_request(request):
            return await call_next(request)

        expected = configured_api_key()
        if not expected:
            return JSONResponse(
                status_code=500,
                content={"detail": "API authentication is enabled but API_KEY is not configured"},
            )

        provided = request.headers.get(api_key_header_name(), "")
        if not hmac.compare_digest(provided, expected):
            return JSONResponse(status_code=401, content={"detail": "Invalid API key"})

        return await call_next(request)
