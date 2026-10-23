"""Health and static data."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from fastapi import APIRouter, Request, Response

from balatro_api import __version__
from balatro_api.application.dto import Catalog
from balatro_api.presentation.http.deps import Uses

router = APIRouter(tags=["meta"])


@router.get("/health", summary="Is the server up")
def health(uses: Uses) -> dict[str, str]:
    cat = uses.catalog()
    return {"status": "ok", "api_version": __version__, "engine_version": cat.engine_version,
            "game_version": cat.game_version}


@router.get("/catalog", response_model=Catalog, summary="Static game data: names, prices, sprites")
def catalog(uses: Uses, request: Request, response: Response) -> Catalog | Response:
    """Every deck, stake, challenge, joker, consumable, voucher, booster,
    enhancement, edition, seal, tag, blind, poker hand and playing card, with
    where the game draws it in its sprite sheets (``atlases`` gives each sheet's
    file in the game's ``resources/textures/1x`` and its cell size). It never
    changes while the server runs, so it is sent with an ETag."""
    cat = uses.catalog()
    etag = '"' + hashlib.sha256(json.dumps(asdict(cat), sort_keys=True).encode()).hexdigest()[:16] + '"'
    headers = {"ETag": etag, "Cache-Control": "public, max-age=3600"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    response.headers.update(headers)
    return cat
