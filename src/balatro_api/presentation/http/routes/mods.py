"""Content mods: check a package, publish it, browse the registry, download
and install mods. Packages are kept by content hash: a run names its mods by
hash (``settings.mods``) and ``GET /mods/packages/{hash}`` gives each back."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Query, Response, status

from balatro_api.application.dto import ModCheck, ModDetailView, ModListView, ModSummaryView
from balatro_api.presentation.http.deps import CurrentPlayer, Uses

router = APIRouter(prefix="/mods", tags=["mods"])
Package = Annotated[dict[str, Any], Body(description="A mod's package: BalatroEngine's content mod format "
                                                     "(docs/mods.md), as JSON")]
IMMUTABLE = "private, max-age=31536000, immutable"


@router.get("", response_model=ModListView, summary="Browse the mods")
def list_mods(player: CurrentPlayer, uses: Uses,
              q: Annotated[str | None, Query(max_length=60, description="in the id, name or description")] = None,
              tag: Annotated[str | None, Query(max_length=24)] = None,
              sort: Literal["popular", "new", "updated", "name"] = "popular",
              mine: Annotated[bool, Query(description="only the mods you published (also unlisted ones)")] = False,
              limit: Annotated[int, Query(ge=1, le=100)] = 30,
              offset: Annotated[int, Query(ge=0)] = 0) -> ModListView:
    return uses.list_mods(player, q, tag, sort, limit, offset, mine)


@router.post("/validate", response_model=ModCheck, summary="Check a package (keeps nothing)")
def validate_mod(package: Package, player: CurrentPlayer, uses: Uses) -> ModCheck:
    """The format first, then a short run played with the mod (its decks, with its jokers, consumables and
    vouchers). ``errors`` name their place in the package (``jokers[0].effects[1].if: unknown name
    'cardd'``)."""
    return uses.validate_mod(player, package)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ModDetailView, summary="Publish a mod")
def publish_mod(package: Package, player: CurrentPlayer, uses: Uses, response: Response) -> ModDetailView:
    """A new mod (its id becomes yours), or a new version of yours (a higher ``version``): 422 invalid_mod
    with its ``errors``, 409 mod_id_taken (another player's id), 409 mod_version_exists. Published versions
    never change."""
    mod = uses.publish_mod(player, package)
    response.headers["Location"] = f"/api/v1/mods/{mod.id}"
    return mod


@router.get("/packages/{package_hash}", response_model=dict[str, Any], summary="A package, by hash")
def mod_package(package_hash: str, player: CurrentPlayer, uses: Uses, response: Response) -> dict[str, Any]:
    """The packages of a run's mods (``settings.mods``), with their images. A package never changes."""
    response.headers["Cache-Control"] = IMMUTABLE
    return uses.mod_package(player, package_hash)


@router.get("/{mod_id}", response_model=ModDetailView, summary="A mod and its versions")
def get_mod(mod_id: str, player: CurrentPlayer, uses: Uses) -> ModDetailView:
    return uses.get_mod(player, mod_id)


@router.get("/{mod_id}/package", response_model=dict[str, Any], summary="Download a mod's package")
def download_mod(mod_id: str, player: CurrentPlayer, uses: Uses,
                 version: Annotated[str | None, Query(max_length=20)] = None) -> dict[str, Any]:
    """Its latest version, or ``version``: the JSON to install, or to save as a file."""
    return uses.download_mod(player, mod_id, version)


@router.post("/{mod_id}/install", response_model=ModSummaryView, summary="Count an install")
def install_mod(mod_id: str, player: CurrentPlayer, uses: Uses) -> ModSummaryView:
    """The player installed the mod: each player counts once in its ``installs``."""
    return uses.install_mod(player, mod_id)


@router.delete("/{mod_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Unlist a mod")
def unlist_mod(mod_id: str, player: CurrentPlayer, uses: Uses) -> Response:
    """Its publisher (or a moderator) takes it off the registry. Its packages stay: runs replay with them."""
    uses.unlist_mod(player, mod_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
