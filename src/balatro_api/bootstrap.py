"""The composition root: the only place that knows every layer.  It picks
the adapters and builds the use cases with them."""

from __future__ import annotations

from .application.locks import RunLocks
from .application.ports import Clock, GameEngine, GameRepository, IdGenerator
from .application.use_cases import (
    CreateGame,
    DeleteGame,
    GetCatalog,
    GetGame,
    GetHistory,
    GetLegalActions,
    ListGames,
    PlayAction,
    PreviewHand,
    RunDebugCommand,
    UseCases,
)
from .config import Settings
from .infrastructure.engine import BalatroEngine
from .infrastructure.persistence import InMemoryGameRepository, SqliteGameRepository
from .infrastructure.system import SystemClock, UuidGenerator


def build_use_cases(settings: Settings, engine: GameEngine | None = None, games: GameRepository | None = None,
                    ids: IdGenerator | None = None, clock: Clock | None = None) -> UseCases:
    engine = engine or BalatroEngine(cache_size=settings.cache_size)
    if games is None:
        games = InMemoryGameRepository() if settings.database == "memory" else SqliteGameRepository(settings.database)
    ids = ids or UuidGenerator()
    clock = clock or SystemClock()
    locks = RunLocks()
    return UseCases(
        create_game=CreateGame(engine, games, ids, clock),
        get_game=GetGame(engine, games),
        list_games=ListGames(games),
        delete_game=DeleteGame(engine, games, locks),
        legal_actions=GetLegalActions(engine, games),
        play_action=PlayAction(engine, games, locks, clock),
        preview_hand=PreviewHand(engine, games),
        history=GetHistory(games),
        debug_command=RunDebugCommand(engine, games, locks, clock, enabled=settings.debug_commands),
        catalog=GetCatalog(engine),
    )
