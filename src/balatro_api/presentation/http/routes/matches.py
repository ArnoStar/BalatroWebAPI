"""Multiplayer matches: a lobby with an invite code, then the players' runs.

PvP: each player plays their own run (``run_id``) with the run routes; the
match keeps them in step. Read the match every second or two while playing:
it shows the other player, the hit points, what each one waits for and the
timer's deadline (and it is when the match catches up with the timer). A
player of another match gets ``404 match_not_found``.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from balatro_api.application.dto import MatchView
from balatro_api.presentation.http.deps import CurrentPlayer, Uses
from balatro_api.presentation.http.schemas import (
    JoinMatchRequest,
    MatchSettingsRequest,
    NewMatchRequest,
    VoteRequest,
)

router = APIRouter(prefix="/matches", tags=["matches"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=MatchView, summary="Make a match")
def create_match(body: NewMatchRequest, player: CurrentPlayer, uses: Uses, response: Response) -> MatchView:
    """A new match in its lobby, with the caller as its host. Its ``code`` lets another player join. The
    caller leaves the lobby they were in; playing another match is ``409 in_a_match``."""
    match = uses.create_match(player, body.to_dto())
    response.headers["Location"] = f"/api/v1/matches/{match.id}"
    return match


@router.post("/join", response_model=MatchView, summary="Join a match with its invite code")
def join_match(body: JoinMatchRequest, player: CurrentPlayer, uses: Uses) -> MatchView:
    return uses.join_match(player, body.code, float(body.game_speed))


@router.get("/current", response_model=MatchView, summary="The caller's match not finished yet",
            responses={204: {"description": "No match"}})
def current_match(player: CurrentPlayer, uses: Uses) -> MatchView | Response:
    match = uses.current_match(player)
    return match if match is not None else Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{match_id}", response_model=MatchView, summary="The match as the player sees it")
def get_match(match_id: str, player: CurrentPlayer, uses: Uses) -> MatchView:
    return uses.get_match(player, match_id)


@router.put("/{match_id}/settings", response_model=MatchView, summary="Change the match's settings (the host)")
def change_settings(match_id: str, body: MatchSettingsRequest, player: CurrentPlayer, uses: Uses) -> MatchView:
    return uses.change_match(player, match_id, body.to_dto())


@router.post("/{match_id}/start", response_model=MatchView, summary="Start the match (the host)")
def start_match(match_id: str, player: CurrentPlayer, uses: Uses) -> MatchView:
    """Each player gets a run of the same seed, deck and stake (everything unlocked)."""
    return uses.start_match(player, match_id)


@router.post("/{match_id}/vote", response_model=MatchView, summary="Play or skip the blind on deck (PvP)")
def vote(match_id: str, body: VoteRequest, player: CurrentPlayer, uses: Uses) -> MatchView:
    """Once both players have chosen (``pvp.vote.decision``), each plays it with ``select_blind`` or
    ``skip_blind``: the blind is skipped only if both chose to skip it."""
    return uses.vote_blind(player, match_id, body.choice)


@router.post("/{match_id}/leave", status_code=status.HTTP_204_NO_CONTENT, summary="Leave the match")
def leave_match(match_id: str, player: CurrentPlayer, uses: Uses) -> Response:
    """Out of the lobby (the host closes it); in a match being played, the other player wins."""
    uses.leave_match(player, match_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
