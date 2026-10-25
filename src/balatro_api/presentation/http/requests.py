"""Every request gets an id (``X-Request-ID``: the client's, or a new one),
sent back in the response and written in the server's log with the request,
so a bug report that recorded it points at the server's side of the story."""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

log = logging.getLogger("balatro_api.requests")
VALID = re.compile(r"[A-Za-z0-9._-]{8,64}")


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_id(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        given = request.headers.get("x-request-id")
        rid = given if given and VALID.fullmatch(given) else uuid.uuid4().hex
        request.state.request_id = rid
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        log.info("%s %s %d %.0fms [%s]", request.method, request.url.path, response.status_code,
                 1000 * (time.perf_counter() - start), rid)
        return response
