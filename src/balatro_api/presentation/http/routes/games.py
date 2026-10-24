"""Runs: create, read, play. A player only sees their own runs (another
player's run is 404 ``game_not_found``)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Query, Response, status

from balatro_api.application.dto import ActionResult, GameSummaryView, GameView, HandPreview, HistoryView, LegalAction
from balatro_api.presentation.http.deps import CurrentPlayer, Uses
from balatro_api.presentation.http.schemas import ActionRequest, DebugRequest, NewGameRequest, PreviewRequest

router = APIRouter(prefix="/games", tags=["games"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=GameView, summary="Start a run")
def create_game(body: NewGameRequest, player: CurrentPlayer, uses: Uses, response: Response) -> GameView:
    """Start a run and play it to the first decision (the blind select
    screen). The same seed, deck, stake and choices always give the same run,
    as in the game."""
    game = uses.create_game(player, body.to_dto())
    response.headers["Location"] = f"/api/v1/games/{game.id}"
    return game


@router.get("", response_model=list[GameSummaryView], summary="List runs, most recently played first")
def list_games(player: CurrentPlayer, uses: Uses, limit: Annotated[int, Query(ge=1, le=200)] = 50,
               offset: Annotated[int, Query(ge=0)] = 0) -> list[GameSummaryView]:
    return uses.list_games(player, limit, offset)


@router.get("/{game_id}", response_model=GameView, summary="The run as the player sees it")
def get_game(game_id: str, player: CurrentPlayer, uses: Uses) -> GameView:
    """Everything on screen, plus ``actions``: what can be done now."""
    return uses.get_game(player, game_id)


@router.delete("/{game_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a run")
def delete_game(game_id: str, player: CurrentPlayer, uses: Uses) -> Response:
    uses.delete_game(player, game_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{game_id}/actions", response_model=list[LegalAction], summary="What the player can do now")
def legal_actions(game_id: str, player: CurrentPlayer, uses: Uses) -> list[LegalAction]:
    return uses.legal_actions(player, game_id)


@router.post("/{game_id}/actions", response_model=ActionResult, summary="Act")
def act(game_id: str, action: Annotated[ActionRequest, Body(discriminator="type")], player: CurrentPlayer,
        uses: Uses) -> ActionResult:
    """Apply one player action, then run the game until it waits for the
    player again. Returns the new state and what the player saw happen, in
    order (``events``). An action the game doesn't allow is refused with 409
    ``illegal_action`` and changes nothing."""
    return uses.play_action(player, game_id, action.to_dto(), action.expected_version)


@router.post("/{game_id}/preview", response_model=HandPreview, summary="The hand these cards make")
def preview_hand(game_id: str, body: PreviewRequest, player: CurrentPlayer, uses: Uses) -> HandPreview:
    """What the game shows while these cards are selected (the poker hand, its
    level, chips and mult, and whether the boss blind forbids it). Changes
    nothing."""
    return uses.preview_hand(player, game_id, body.cards)


@router.get("/{game_id}/history", response_model=HistoryView, summary="The run's commands")
def history(game_id: str, player: CurrentPlayer, uses: Uses) -> HistoryView:
    """The run as stored: its settings and every accepted command, in the
    engine's format. Replaying them gives the same run (for bug reports and
    for checking a run against the original game with BalatroEngine's oracle)."""
    return uses.history(player, game_id)


@router.post("/{game_id}/debug", response_model=ActionResult, summary="Test helper (when enabled)")
def debug(game_id: str, body: DebugRequest, player: CurrentPlayer, uses: Uses) -> ActionResult:
    """Only when the server runs with BALATRO_API_DEBUG_COMMANDS=1."""
    return uses.debug_command(player, game_id, body.command, body.expected_version)
