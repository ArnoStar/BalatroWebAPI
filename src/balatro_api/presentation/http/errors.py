"""Errors as RFC 9457 problem details: ``{type, title, status, detail, code}``.
``code`` is stable; clients should switch on it."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from balatro_api.application.errors import AuthUnavailable, DebugCommandsDisabled, ImportForbidden, NotAuthenticated
from balatro_api.domain import DomainError, GameNotFound, IllegalAction, InvalidGameSettings, VersionConflict

log = logging.getLogger(__name__)

STATUS: list[tuple[type[DomainError], int]] = [
    (GameNotFound, 404),
    (VersionConflict, 409),
    (IllegalAction, 409),  # (and GameOver): not possible in the game's current state
    (InvalidGameSettings, 422),
    (DebugCommandsDisabled, 403),
    (ImportForbidden, 403),
    (NotAuthenticated, 401),
    (AuthUnavailable, 503),
]
TITLES = {401: "Unauthorized", 404: "Not Found", 409: "Conflict", 422: "Unprocessable Content", 403: "Forbidden",
          500: "Internal Server Error", 503: "Service Unavailable"}


def problem(status: int, code: str, detail: str, headers: dict[str, str] | None = None, **extra: Any) -> JSONResponse:
    body = {"type": f"https://balatro-api/errors/{code}", "title": TITLES.get(status, "Error"), "status": status,
            "detail": detail, "code": code, **extra}
    return JSONResponse(body, status_code=status, headers=headers, media_type="application/problem+json")


def install(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError) -> JSONResponse:
        status = next((s for cls, s in STATUS if isinstance(exc, cls)), 400)
        extra: dict[str, Any] = {}
        if isinstance(exc, VersionConflict):
            extra = {"expected_version": exc.expected, "current_version": exc.actual}
        headers = {"WWW-Authenticate": 'Bearer error="invalid_token"'} if isinstance(exc, NotAuthenticated) else None
        return problem(status, exc.code, exc.message, headers, **extra)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"loc": list(e.get("loc", ())), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return problem(422, "invalid_request", "the request doesn't match the schema", errors=errors)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        rid = getattr(request.state, "request_id", None)
        log.exception("unexpected error in %s %s [%s]", request.method, request.url.path, rid, exc_info=exc)
        headers = {"X-Request-ID": rid} if rid else None
        return problem(500, "internal_error", "unexpected server error", headers, request_id=rid)
