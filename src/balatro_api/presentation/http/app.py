"""The FastAPI application."""

from __future__ import annotations

from collections.abc import Sequence

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from balatro_api import __version__
from balatro_api.application.use_cases import UseCases

from . import errors, requests
from .routes import games, meta, stats

DESCRIPTION = """
Play Balatro runs over HTTP. The game logic is BalatroEngine's, which
reproduces the original game exactly: the same seed and the same choices give
the same run as in the game.

A run waits for one decision at a time (`phase`). Read it with
`GET /games/{id}`; its `actions` list what can be done. Send one with
`POST /games/{id}/actions`. Cards are referred to by `id`.

When the server runs with sign-in (`GET /health` says `"auth": "required"`),
every game route needs an access token from the identity service
(`Authorization: Bearer ...`), and a player only sees their own runs.

Statistics (`/stats/me`, `/stats/global`, `/leaderboards/{board}`) count the
runs as the game's profile does: a run whose seed the player chose, or a
challenge, doesn't count (nor, here, a run that used debug commands).
"""


def create_app(use_cases: UseCases, cors_origins: Sequence[str] = ("*",)) -> FastAPI:
    app = FastAPI(title="Balatro Web API", version=__version__, description=DESCRIPTION)
    app.state.use_cases = use_cases
    app.add_middleware(CORSMiddleware, allow_origins=list(cors_origins), allow_methods=["*"], allow_headers=["*"],
                       expose_headers=["ETag", "Location", "WWW-Authenticate", "X-Request-ID"])
    errors.install(app)
    requests.install(app)
    api = APIRouter(prefix="/api/v1")
    api.include_router(meta.router)
    api.include_router(games.router)
    api.include_router(stats.router)
    app.include_router(api)

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("/docs")

    return app
