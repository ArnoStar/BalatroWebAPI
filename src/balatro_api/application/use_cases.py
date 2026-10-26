"""The use cases: one class per thing a client can do.

Every use case acts for a player (``Player``, from the access token): a
player only plays their own runs; someone else's run is "not found", as if
it didn't exist. Others may watch a run once it is finished, unless its
owner's profile is private (``viewable_run``).

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

from balatro_api.domain import Command, GameNotFound, GameSettings, Phase, Progress, Run, RunSummary

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
    MeView,
    NewGame,
    Player,
    PlayerAction,
    PlayerProfileView,
    PlayerSettings,
    PlayerStats,
    ReplayStep,
    SettingsView,
    WatchView,
)
from .errors import DebugCommandsDisabled, ImportForbidden, PlayerNotFound, UnlockAllForbidden
from .locks import RunLocks
from .permissions import Permission, allowed
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


def is_private(games: GameRepository, player_id: str) -> bool:
    record = games.player(player_id)
    return record is not None and record.private


def viewable_run(games: GameRepository, player: Player, game_id: str) -> Run:
    """A run the player may watch: their own, or a finished run of a player whose profile is
    public (developers and admins: any run). Any other run is "not found"."""
    run = games.get(game_id)
    if run.owned_by(player.id) or allowed(player, Permission.WATCH_ALL):
        return run
    if run.finished and not run.replay and not is_private(games, run.owner):
        return run
    raise GameNotFound(game_id)


def summary_view(r: RunSummary) -> GameSummaryView:
    return GameSummaryView(id=r.id, version=r.version, settings=settings_view(r.settings), phase=r.progress.phase,
                           ante=r.progress.ante, round=r.progress.round, dollars=r.progress.dollars,
                           won=r.progress.won, created_at=r.created_at, updated_at=r.updated_at,
                           best_hand=score(r.stats.best_hand), counted=r.counts)


def can_unlock_all(player: Player, debug_enabled: bool) -> bool:
    """The roles that test the game (or anyone, on a server with debug commands)."""
    return debug_enabled or allowed(player, Permission.UNLOCK_ALL)


def start_profile(engine: GameEngine, games: GameRepository, player: Player, debug_enabled: bool) -> dict[str, Any]:
    """What a new run of the player's starts from: their progress, or everything when they have
    switched "unlock everything" on (and may)."""
    record = games.player(player.id)
    if record is not None and record.all_unlocked and can_unlock_all(player, debug_enabled):
        return {"all": True}
    return engine.player_progress(games.runs_of(player.id))


class Authenticate:
    def __init__(self, authenticator: Authenticator) -> None:
        self.authenticator = authenticator

    @property
    def required(self) -> bool:
        return self.authenticator.required

    def __call__(self, token: str | None) -> Player:
        return self.authenticator.authenticate(token)


class CreateGame:
    def __init__(self, engine: GameEngine, games: GameRepository, ids: IdGenerator, clock: Clock,
                 debug_enabled: bool = False) -> None:
        self.engine, self.games, self.ids, self.clock = engine, games, ids, clock
        self.debug_enabled = debug_enabled

    def __call__(self, player: Player, request: NewGame) -> GameView:
        settings = self.engine.check_settings(GameSettings(
            seed=request.seed if request.seed is not None else self.engine.random_seed(),
            deck=request.deck, stake=request.stake, challenge=request.challenge, game_speed=request.game_speed,
            seeded=request.seed is not None))
        profile = start_profile(self.engine, self.games, player, self.debug_enabled)
        self.engine.check_unlocked(settings, profile)
        run_id = self.ids.new_id()
        progress = self.engine.start(run_id, settings, profile)
        now = self.clock.now()
        run = Run(id=run_id, settings=settings, engine_version=self.engine.version, progress=progress,
                  created_at=now, updated_at=now, owner=player.id, owner_name=player.name, start_profile=profile)
        run.stats = self.engine.run_stats(run)
        self.games.add(run)
        return self.engine.view(run)


class ImportGame:
    """Rebuild a run from its settings and commands, as the caller's run (to
    reproduce a bug report).  For accounts allowed to (their roles, or the
    BALATRO_API_ADMINS list), or anyone on a server with debug commands.  The
    new run doesn't count for statistics, and it isn't listed with the caller's
    runs (it is the reporter's run, seen again)."""

    def __init__(self, engine: GameEngine, games: GameRepository, ids: IdGenerator, clock: Clock,
                 debug_enabled: bool, admins: Sequence[str]) -> None:
        self.engine, self.games, self.ids, self.clock = engine, games, ids, clock
        self.debug_enabled, self.admins = debug_enabled, frozenset(admins)

    def __call__(self, player: Player, request: ImportedRun) -> GameView:
        if not (self.debug_enabled or player.id in self.admins or allowed(player, Permission.IMPORT_RUNS)):
            raise ImportForbidden()
        settings = self.engine.check_settings(GameSettings(
            seed=request.seed, deck=request.deck, stake=request.stake, challenge=request.challenge,
            game_speed=request.game_speed, seeded=request.seeded))
        now = self.clock.now()
        run = Run(id=self.ids.new_id(), settings=settings, engine_version=self.engine.version,
                  progress=Progress(Phase.BLIND_SELECT, 1, 0, 0, False),  # (replaced by the replay's)
                  created_at=now, updated_at=now,
                  commands=[Command(c) for c in request.commands], owner=player.id, owner_name=player.name,
                  debug=True, replay=True, start_profile=request.start_profile)
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
        return [summary_view(r) for r in self.games.list(player.id, limit, offset)]


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
        run = viewable_run(self.games, player, game_id)
        return HistoryView(id=run.id, version=run.version, engine_version=run.engine_version,
                           settings=settings_view(run.settings), commands=[c.as_dict() for c in run.commands],
                           start_profile=run.start_profile)


class WatchGame:
    """Watch a run again: a copy of it at its start (the caller's, not listed and not counted)
    and its actions, to play on the copy with their animations."""

    def __init__(self, engine: GameEngine, games: GameRepository, ids: IdGenerator, clock: Clock) -> None:
        self.engine, self.games, self.ids, self.clock = engine, games, ids, clock

    def __call__(self, player: Player, game_id: str) -> WatchView:
        source = viewable_run(self.games, player, game_id)
        steps = self.engine.replay_steps(source)
        copy_id = self.ids.new_id()
        progress = self.engine.start(copy_id, source.settings, source.start_profile)
        now = self.clock.now()
        copy = Run(id=copy_id, settings=source.settings, engine_version=self.engine.version, progress=progress,
                   created_at=now, updated_at=now, owner=player.id, owner_name=player.name, debug=True, replay=True,
                   start_profile=source.start_profile)
        copy.stats = self.engine.run_stats(copy)
        self.games.add(copy)
        owner = self.games.player(source.owner)
        return WatchView(source=source.id, owner_name=owner.name if owner else source.owner_name,
                         game=self.engine.view(copy),
                         steps=[ReplayStep(version=i, action=a) for i, a in enumerate(steps)])


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
        if action.type == "continue":
            # (recorded only when continuing changes the run: otherwise the history would fill with no-ops)
            run = owned_run(self.games, player, game_id)
            if run.finished or not self.engine.continues(run):
                return ActionResult(game=self.engine.view(run), events=[])
        return self._change(player, game_id, expected_version, lambda run: self.engine.apply(run, action))


class RunDebugCommand(_ChangeRun):
    """Test helpers (give money, add a joker, force a boss ...): on a server
    with debug commands, or for the accounts whose roles allow them (testers).
    They are recorded like actions, so the run still replays; the run then
    doesn't count for statistics."""

    def __init__(self, engine: GameEngine, games: GameRepository, locks: RunLocks, clock: Clock,
                 enabled: bool) -> None:
        super().__init__(engine, games, locks, clock)
        self.enabled = enabled

    def __call__(self, player: Player, game_id: str, command: dict[str, Any],
                 expected_version: int | None = None) -> ActionResult:
        # (a replay may play the debug commands of the run it copies)
        if not (self.enabled or allowed(player, Permission.DEBUG_COMMANDS)) and not owned_run(
                self.games, player, game_id).replay:
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
    """Everyone's best counted runs, with the players' names and profile ids."""

    def __init__(self, games: GameRepository) -> None:
        self.games = games

    def __call__(self, player: Player, board: LeaderboardName, deck: str | None = None, stake: int | None = None,
                 limit: int = 50) -> Leaderboard:
        page = self.games.leaderboard(board, deck, stake, limit, player.id)

        def entry(r: BoardRow) -> LeaderboardEntry:
            return LeaderboardEntry(rank=r.rank, player=r.name, you=r.owner == player.id, value=score(r.value),
                                    deck=r.deck, stake=r.stake, won=r.won, achieved_at=r.at, player_id=r.owner)

        top = [entry(r) for r in page.rows[:limit]]  # (the caller's row comes last when it isn't in the top)
        mine = next((entry(r) for r in page.rows if r.owner == player.id), None)
        return Leaderboard(board=board, deck=deck, stake=stake, players=page.players, entries=top, you=mine)


class GetMe:
    """The caller's account here: their settings and progress (what the game shows as unlocked)."""

    def __init__(self, engine: GameEngine, games: GameRepository, debug_enabled: bool = False) -> None:
        self.engine, self.games, self.debug_enabled = engine, games, debug_enabled

    def __call__(self, player: Player) -> MeView:
        record = self.games.player(player.id)
        can = can_unlock_all(player, self.debug_enabled)
        profile = self.engine.player_progress(self.games.runs_of(player.id))
        return MeView(id=player.id, name=player.name or (record.name if record else None),
                      private=bool(record and record.private),
                      progress=self.engine.progress_view(profile, bool(record and record.all_unlocked and can), can))


class UpdateMe:
    def __init__(self, games: GameRepository, me: GetMe) -> None:
        self.games, self.me = games, me

    def __call__(self, player: Player, changes: PlayerSettings) -> MeView:
        if changes.all_unlocked and not can_unlock_all(player, self.me.debug_enabled):
            raise UnlockAllForbidden()
        self.games.set_player(player.id, player.name, private=changes.private, all_unlocked=changes.all_unlocked)
        return self.me(player)


class GetPlayerProfile:
    """A player's profile: stats, collection and recent runs (others see only finished runs;
    a private profile shows only the name)."""

    def __init__(self, engine: GameEngine, games: GameRepository, clock: Clock) -> None:
        self.engine, self.games, self.clock = engine, games, clock

    def __call__(self, player: Player, player_id: str, limit: int = 20) -> PlayerProfileView:
        record = self.games.player(player_id)
        runs = self.games.runs_of(player_id)
        if record is None and not runs:
            raise PlayerNotFound(player_id)
        you = player_id == player.id
        name = record.name if record else None
        private = bool(record and record.private)
        if private and not (you or allowed(player, Permission.WATCH_ALL)):
            return PlayerProfileView(id=player_id, name=name, you=you, private=True)
        recent = [r for r in self.games.list(player_id, 200, 0) if you or r.finished][:limit]
        return PlayerProfileView(
            id=player_id, name=name, you=you, private=private, stats=player_stats(runs, self.clock.now()),
            collection=self.engine.collection(self.engine.player_progress(runs)),
            runs=[summary_view(r) for r in recent])


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
    watch_game: WatchGame
    me: GetMe
    update_me: UpdateMe
    player_profile: GetPlayerProfile


__all__ = ["Authenticate", "CreateGame", "DeleteGame", "GetCatalog", "GetGame", "GetGlobalStats", "GetHistory",
           "GetLeaderboard", "GetLegalActions", "GetMe", "GetPlayerProfile", "GetPlayerStats", "ImportGame",
           "ListGames", "PlayAction", "PreviewHand", "RunDebugCommand", "UpdateMe", "UseCases", "WatchGame"]
