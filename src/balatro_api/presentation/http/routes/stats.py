"""Statistics: the caller's profile stats, leaderboards, and everyone's runs
together. As in the game, only runs whose seed the player didn't choose and
that aren't challenges count (and here, runs without debug commands)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from balatro_api.application.dto import GlobalStats, Leaderboard, LeaderboardName, PlayerStats
from balatro_api.presentation.http.deps import CurrentPlayer, Uses

router = APIRouter(tags=["statistics"])


@router.get("/stats/me", response_model=PlayerStats, summary="The caller's statistics")
def player_stats(player: CurrentPlayer, uses: Uses) -> PlayerStats:
    """The game's Profile > Stats: high scores, career stats, and how often
    each poker hand, joker, consumable, voucher and deck was used."""
    return uses.player_stats(player)


@router.get("/stats/global", response_model=GlobalStats, summary="Everyone's runs together")
def global_stats(player: CurrentPlayer, uses: Uses) -> GlobalStats:
    return uses.global_stats(player)


@router.get("/leaderboards/{board}", response_model=Leaderboard, summary="A leaderboard")
def leaderboard(board: LeaderboardName, player: CurrentPlayer, uses: Uses,
                deck: Annotated[str | None, Query(description="only runs with this deck (b_red ...)")] = None,
                stake: Annotated[int | None, Query(ge=1, le=8, description="only runs at this stake")] = None,
                limit: Annotated[int, Query(ge=1, le=200)] = 50) -> Leaderboard:
    """Each player's best run (for ``wins``: their number of won runs), best
    first, with the caller's own entry in ``you``. Players are shown by their
    display name only."""
    return uses.leaderboard(player, board, deck, stake, limit)
