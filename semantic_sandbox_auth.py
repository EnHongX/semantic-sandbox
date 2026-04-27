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


def _safe_audit_log(request: Request, *, event: str, level: str, metadata: dict | None = None) -> None:
    try:
        from semantic_sandbox_common import append_audit_log, request_log_context
        from semantic_sandbox_postgres import current_vector_backend

        append_audit_log({
            **request_log_context(request),
            "event": event,
            "level": level,
            "actor": "api-key",
            "backend": current_vector_backend(""),
            "target_type": "api",
            "target_id": request.url.path,
            "metadata": metadata or {},
        })
    except Exception:
        return


def install_api_key_auth(app: FastAPI) -> None:
    @app.middleware("http")
    async def api_key_auth(request: Request, call_next: Callable[[Request], Awaitable]):
        if not auth_enabled() or not request.url.path.startswith("/api/") or _is_public_api_request(request):
            return await call_next(request)

        expected = configured_api_key()
        if not expected:
            _safe_audit_log(
                request,
                event="api_key_config_missing",
                level="error",
                metadata={"header_name": api_key_header_name()},
            )
            return JSONResponse(
                status_code=500,
                content={"detail": "API authentication is enabled but API_KEY is not configured"},
            )

        provided = request.headers.get(api_key_header_name(), "")
        if not hmac.compare_digest(provided, expected):
            _safe_audit_log(
                request,
                event="api_key_invalid",
                level="warning",
                metadata={"header_name": api_key_header_name(), "header_present": bool(provided)},
            )
            return JSONResponse(status_code=401, content={"detail": "Invalid API key"})

        return await call_next(request)
