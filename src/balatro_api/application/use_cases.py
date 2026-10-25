"""The use cases: one class per thing a client can do.

Every use case acts for a player (``Player``, from the access token): a
player only sees and plays their own runs; someone else's run is "not
found", as if it didn't exist.

Every change to a run follows the same steps, under the run's lock: load
the run, check the client's version, let the engine play the action on a
copy of the game, record the command, save the run (optimistic: fails if
someone else saved first), and only then make the copy the run's game.  An
action that fails at any step leaves the run as it was.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from balatro_api.domain import Command, GameNotFound, GameSettings, Phase, Progress, Run

from .dto import (
    ActionResult,
    Catalog,
    GameSummaryView,
    GameView,
    GlobalStats,
    HandPreview,
    HistoryView,
    ImportedRun,
    Leaderboard,
    LeaderboardEntry,
    LeaderboardName,
    LegalAction,
    NewGame,
    Player,
    PlayerAction,
    PlayerStats,
    SettingsView,
)
from .errors import DebugCommandsDisabled, ImportForbidden
from .locks import RunLocks
from .ports import Authenticator, BoardRow, Clock, GameEngine, GameRepository, IdGenerator, Outcome
from .statistics import player_stats, score


def settings_view(s: GameSettings) -> SettingsView:
    return SettingsView(seed=s.seed, deck=s.deck, stake=s.stake, challenge=s.challenge, game_speed=s.game_speed,
                        seeded=s.seeded)


def owned_run(games: GameRepository, player: Player, game_id: str) -> Run:
    run = games.get(game_id)
    if not run.owned_by(player.id):
        raise GameNotFound(game_id)
    return run


class Authenticate:
    def __init__(self, authenticator: Authenticator) -> None:
        self.authenticator = authenticator

    @property
    def required(self) -> bool:
        return self.authenticator.required

    def __call__(self, token: str | None) -> Player:
        return self.authenticator.authenticate(token)


class CreateGame:
    def __init__(self, engine: GameEngine, games: GameRepository, ids: IdGenerator, clock: Clock) -> None:
        self.engine, self.games, self.ids, self.clock = engine, games, ids, clock

    def __call__(self, player: Player, request: NewGame) -> GameView:
        settings = self.engine.check_settings(GameSettings(
            seed=request.seed if request.seed is not None else self.engine.random_seed(),
            deck=request.deck, stake=request.stake, challenge=request.challenge, game_speed=request.game_speed,
            seeded=request.seed is not None))
        run_id = self.ids.new_id()
        progress = self.engine.start(run_id, settings)
        now = self.clock.now()
        run = Run(id=run_id, settings=settings, engine_version=self.engine.version, progress=progress,
                  created_at=now, updated_at=now, owner=player.id, owner_name=player.name)
        run.stats = self.engine.run_stats(run)
        self.games.add(run)
        return self.engine.view(run)


class ImportGame:
    """Rebuild a run from its settings and commands, as the caller's run (to
    reproduce a bug report).  Only for admins, or on a server with debug
    commands.  The new run doesn't count for statistics."""

    def __init__(self, engine: GameEngine, games: GameRepository, ids: IdGenerator, clock: Clock,
                 debug_enabled: bool, admins: Sequence[str]) -> None:
        self.engine, self.games, self.ids, self.clock = engine, games, ids, clock
        self.debug_enabled, self.admins = debug_enabled, frozenset(admins)

    def __call__(self, player: Player, request: ImportedRun) -> GameView:
        if not (self.debug_enabled or player.id in self.admins):
            raise ImportForbidden()
        settings = self.engine.check_settings(GameSettings(
            seed=request.seed, deck=request.deck, stake=request.stake, challenge=request.challenge,
            game_speed=request.game_speed, seeded=True))
        now = self.clock.now()
        run = Run(id=self.ids.new_id(), settings=settings, engine_version=self.engine.version,
                  progress=Progress(Phase.BLIND_SELECT, 1, 0, 0, False),  # (replaced by the replay's)
                  created_at=now, updated_at=now,
                  commands=[Command(c) for c in request.commands], owner=player.id, owner_name=player.name,
                  debug=True)
        try:
            run.progress, run.stats = self.engine.load(run)
        except Exception:
            self.engine.forget(run.id)
            raise
        self.games.add(run)
        return self.engine.view(run)


class GetGame:
    def __init__(self, engine: GameEngine, games: GameRepository) -> None:
        self.engine, self.games = engine, games

    def __call__(self, player: Player, game_id: str) -> GameView:
        return self.engine.view(owned_run(self.games, player, game_id))


class ListGames:
    def __init__(self, games: GameRepository) -> None:
        self.games = games

    def __call__(self, player: Player, limit: int = 50, offset: int = 0) -> list[GameSummaryView]:
        return [GameSummaryView(id=r.id, version=r.version, settings=settings_view(r.settings), phase=r.progress.phase,
                                ante=r.progress.ante, round=r.progress.round, dollars=r.progress.dollars,
                                won=r.progress.won, created_at=r.created_at, updated_at=r.updated_at,
                                best_hand=score(r.stats.best_hand), counted=r.counts)
                for r in self.games.list(player.id, limit, offset)]


class DeleteGame:
    def __init__(self, engine: GameEngine, games: GameRepository, locks: RunLocks) -> None:
        self.engine, self.games, self.locks = engine, games, locks

    def __call__(self, player: Player, game_id: str) -> None:
        with self.locks.hold(game_id):
            owned_run(self.games, player, game_id)
            self.games.delete(game_id)
            self.engine.forget(game_id)


class GetLegalActions:
    def __init__(self, engine: GameEngine, games: GameRepository) -> None:
        self.engine, self.games = engine, games

    def __call__(self, player: Player, game_id: str) -> list[LegalAction]:
        return self.engine.legal_actions(owned_run(self.games, player, game_id))


class PreviewHand:
    def __init__(self, engine: GameEngine, games: GameRepository) -> None:
        self.engine, self.games = engine, games

    def __call__(self, player: Player, game_id: str, cards: Sequence[int]) -> HandPreview:
        return self.engine.preview_hand(owned_run(self.games, player, game_id), cards)


class GetHistory:
    def __init__(self, games: GameRepository) -> None:
        self.games = games

    def __call__(self, player: Player, game_id: str) -> HistoryView:
        run = owned_run(self.games, player, game_id)
        return HistoryView(id=run.id, version=run.version, engine_version=run.engine_version,
                           settings=settings_view(run.settings), commands=[c.as_dict() for c in run.commands])


class _ChangeRun:
    def __init__(self, engine: GameEngine, games: GameRepository, locks: RunLocks, clock: Clock) -> None:
        self.engine, self.games, self.locks, self.clock = engine, games, locks, clock

    def _change(self, player: Player, game_id: str, expected_version: int | None,
                play: Callable[[Run], Outcome], debug: bool = False) -> ActionResult:
        with self.locks.hold(game_id):
            run = owned_run(self.games, player, game_id)
            run.check_version(expected_version)
            run.check_playable()
            outcome = play(run)
            version = run.version
            run.record(outcome.command, outcome.progress, self.clock.now(), stats=outcome.stats, debug=debug)
            run.owner_name = player.name or run.owner_name
            self.games.save(run, expected_version=version)
            self.engine.commit(run, outcome)
            return ActionResult(game=self.engine.view(run), events=outcome.events)


class PlayAction(_ChangeRun):
    def __call__(self, player: Player, game_id: str, action: PlayerAction,
                 expected_version: int | None = None) -> ActionResult:
        return self._change(player, game_id, expected_version, lambda run: self.engine.apply(run, action))


class RunDebugCommand(_ChangeRun):
    """Test helpers for front-end development (give money, add a joker, force
    a boss ...).  They are recorded like actions, so the run still replays."""

    def __init__(self, engine: GameEngine, games: GameRepository, locks: RunLocks, clock: Clock,
                 enabled: bool) -> None:
        super().__init__(engine, games, locks, clock)
        self.enabled = enabled

    def __call__(self, player: Player, game_id: str, command: dict[str, Any],
                 expected_version: int | None = None) -> ActionResult:
        if not self.enabled:
            raise DebugCommandsDisabled()
        return self._change(player, game_id, expected_version, lambda run: self.engine.apply_debug(run, command),
                            debug=True)


class GetCatalog:
    def __init__(self, engine: GameEngine) -> None:
        self.engine = engine

    def __call__(self) -> Catalog:
        return self.engine.catalog()


class GetPlayerStats:
    """The caller's profile statistics (their counted runs)."""

    def __init__(self, games: GameRepository, clock: Clock) -> None:
        self.games, self.clock = games, clock

    def __call__(self, player: Player) -> PlayerStats:
        return player_stats(self.games.runs_of(player.id), self.clock.now())


class GetLeaderboard:
    """Everyone's best counted runs. Only display names are shown: never
    another player's id or run."""

    def __init__(self, games: GameRepository) -> None:
        self.games = games

    def __call__(self, player: Player, board: LeaderboardName, deck: str | None = None, stake: int | None = None,
                 limit: int = 50) -> Leaderboard:
        page = self.games.leaderboard(board, deck, stake, limit, player.id)

        def entry(r: BoardRow) -> LeaderboardEntry:
            return LeaderboardEntry(rank=r.rank, player=r.name, you=r.owner == player.id, value=score(r.value),
                                    deck=r.deck, stake=r.stake, won=r.won, achieved_at=r.at)

        top = [entry(r) for r in page.rows[:limit]]  # (the caller's row comes last when it isn't in the top)
        mine = next((entry(r) for r in page.rows if r.owner == player.id), None)
        return Leaderboard(board=board, deck=deck, stake=stake, players=page.players, entries=top, you=mine)


class GetGlobalStats:
    def __init__(self, games: GameRepository) -> None:
        self.games = games

    def __call__(self, player: Player) -> GlobalStats:
        return self.games.global_stats()


@dataclass(frozen=True)
class UseCases:
    """Everything a client can do (what the presentation layer is given)."""

    authenticate: Authenticate
    create_game: CreateGame
    import_game: ImportGame
    get_game: GetGame
    list_games: ListGames
    delete_game: DeleteGame
    legal_actions: GetLegalActions
    play_action: PlayAction
    preview_hand: PreviewHand
    history: GetHistory
    debug_command: RunDebugCommand
    catalog: GetCatalog
    player_stats: GetPlayerStats
    leaderboard: GetLeaderboard
    global_stats: GetGlobalStats


__all__ = ["Authenticate", "CreateGame", "DeleteGame", "GetCatalog", "GetGame", "GetGlobalStats", "GetHistory",
           "GetLeaderboard", "GetLegalActions", "GetPlayerStats", "ImportGame", "ListGames", "PlayAction",
           "PreviewHand", "RunDebugCommand", "UseCases"]
