"""Players: one's own account here (settings, progress), and players' public profiles."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from balatro_api.application.dto import MeView, PlayerProfileView
from balatro_api.presentation.http.deps import CurrentPlayer, Uses
from balatro_api.presentation.http.schemas import PlayerSettingsRequest

router = APIRouter(prefix="/players", tags=["players"])


@router.get("/me", response_model=MeView, summary="Your settings and progress")
def me(player: CurrentPlayer, uses: Uses) -> MeView:
    """``progress``: what you have unlocked and discovered, as the game's profile keeps it (a new
    account starts like a new save). New runs start from it: a locked deck, stake or challenge is
    ``409 locked``."""
    return uses.me(player)


@router.patch("/me", response_model=MeView, summary="Change your settings")
def update_me(body: PlayerSettingsRequest, player: CurrentPlayer, uses: Uses) -> MeView:
    """``private``: only your name shows on your profile, and others can't watch your runs.
    ``all_unlocked`` (tester, developer and admin roles, or anyone on a server with debug commands;
    ``403 unlock_all_forbidden`` otherwise):
    your new runs start fully unlocked, and add nothing to your progress, which stays as it is."""
    return uses.update_me(player, body.to_dto())


@router.get("/{player_id}", response_model=PlayerProfileView, summary="A player's profile")
def player_profile(player_id: str, player: CurrentPlayer, uses: Uses,
                   limit: Annotated[int, Query(ge=1, le=100)] = 20) -> PlayerProfileView:
    """Stats, collection and recent runs (another player's: finished ones, which can be watched).
    A private profile shows only the name. Unknown player: ``404 player_not_found``."""
    return uses.player_profile(player, player_id, limit)
