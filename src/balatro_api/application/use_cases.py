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

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from balatro_api.domain import Command, GameNotFound, GameSettings, IllegalAction, Phase, Progress, Run, RunSummary

from .dto import (
    ActionResult,
    Catalog,
    CoopDecksView,
    CoopStep,
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
from .matches import (
    ChangeMatchSettings,
    CreateMatch,
    CurrentMatch,
    GetMatch,
    GetMatchHistory,
    GetMultiplayerStats,
    GetSteps,
    JoinMatch,
    KickPlayer,
    LeaveMatch,
    Matches,
    Rematch,
    SendEmote,
    SetSelection,
    StartMatch,
    VoteBlind,
    multiplayer_stats,
)
from .permissions import Permission, allowed
from .ports import Authenticator, BoardRow, Clock, GameEngine, GameRepository, IdGenerator, Outcome
from .statistics import player_stats, score

log = logging.getLogger(__name__)

PROFILE_MATCHES = 10  # the latest matches a profile shows


def action_dict(a: PlayerAction) -> dict[str, Any]:
    """An action as POST /games/{id}/actions takes it (the fields it uses)."""
    d: dict[str, Any] = {"type": a.type}
    if a.cards:
        d["cards"] = list(a.cards)
    if a.card is not None:
        d["card"] = a.card
    if a.targets is not None:
        d["targets"] = list(a.targets)
    if a.use:
        d["use"] = True
    if a.type == "sort":
        d["mode"] = a.mode
    if a.to is not None:
        d["to"] = a.to
    return d


def settings_view(s: GameSettings) -> SettingsView:
    return SettingsView(seed=s.seed, deck=s.deck, stake=s.stake, challenge=s.challenge, game_speed=s.game_speed,
                        seeded=s.seeded, mode=s.mode)


def owned_run(games: GameRepository, player: Player, game_id: str) -> Run:
    run = games.get(game_id)
    if not run.owned_by(player.id):
        raise GameNotFound(game_id)
    return run


def member_run(games: GameRepository, matches: Matches | None, player: Player, game_id: str) -> tuple[Run, int | None]:
    """A run the player plays: their own, or the coop run of a match they are in (with their seat in it).
    Any other run is "not found"."""
    run = games.get(game_id)
    if run.match_id is None or matches is None or run.settings.mode != "coop":
        if not run.owned_by(player.id):
            raise GameNotFound(game_id)
        return run, None
    match = matches.matches.get_match(run.match_id)
    seat = match.seat_of(player.id)
    if seat is None:
        raise GameNotFound(game_id)
    return run, seat


def is_private(games: GameRepository, player_id: str) -> bool:
    record = games.player(player_id)
    return record is not None and record.private


def viewable_run(games: GameRepository, player: Player, game_id: str, matches: Matches | None = None) -> Run:
    """A run the player may watch: their own, or a finished run of a player whose profile is
    public (developers and admins: any run). Once a match is over, its players may watch its runs
    (each other's, played on the same seed). Any other run is "not found"."""
    run = games.get(game_id)
    if run.owned_by(player.id) or allowed(player, Permission.WATCH_ALL):
        return run
    if run.match_id is not None and matches is not None:
        match = matches.matches.get_match(run.match_id)
        if match.played and match.seat_of(player.id) is not None:
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
    def __init__(self, engine: GameEngine, games: GameRepository, matches: Matches | None = None) -> None:
        self.engine, self.games, self.matches = engine, games, matches

    def __call__(self, player: Player, game_id: str) -> GameView:
        run, seat = member_run(self.games, self.matches, player, game_id)
        return self.engine.view(run, seat)


class GetGameSummary:
    """One of the caller's runs as the run list shows it (other services read it with the player's
    token: the social service, to share a run)."""

    def __init__(self, games: GameRepository) -> None:
        self.games = games

    def __call__(self, player: Player, game_id: str) -> GameSummaryView:
        return summary_view(owned_run(self.games, player, game_id).summary())


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
            if owned_run(self.games, player, game_id).match_id is not None:
                raise IllegalAction("a match's run stays with the match")
            self.games.delete(game_id)
            self.engine.forget(game_id)


class GetLegalActions:
    def __init__(self, engine: GameEngine, games: GameRepository, matches: Matches | None = None) -> None:
        self.engine, self.games, self.matches = engine, games, matches

    def __call__(self, player: Player, game_id: str) -> list[LegalAction]:
        run, seat = member_run(self.games, self.matches, player, game_id)
        return self.engine.legal_actions(run, seat)


class PreviewHand:
    def __init__(self, engine: GameEngine, games: GameRepository, matches: Matches | None = None) -> None:
        self.engine, self.games, self.matches = engine, games, matches

    def __call__(self, player: Player, game_id: str, cards: Sequence[int]) -> HandPreview:
        return self.engine.preview_hand(member_run(self.games, self.matches, player, game_id)[0], cards)


class GetHistory:
    def __init__(self, games: GameRepository, matches: Matches | None = None) -> None:
        self.games, self.matches = games, matches

    def __call__(self, player: Player, game_id: str) -> HistoryView:
        run = viewable_run(self.games, player, game_id, self.matches)
        return HistoryView(id=run.id, version=run.version, engine_version=run.engine_version,
                           settings=settings_view(run.settings), commands=[c.as_dict() for c in run.commands],
                           start_profile=run.start_profile)


class WatchGame:
    """Watch a run again: a copy of it at its start (the caller's, not listed and not counted)
    and its actions, to play on the copy with their animations."""

    def __init__(self, engine: GameEngine, games: GameRepository, ids: IdGenerator, clock: Clock,
                 matches: Matches | None = None) -> None:
        self.engine, self.games, self.ids, self.clock = engine, games, ids, clock
        self.matches = matches

    def __call__(self, player: Player, game_id: str) -> WatchView:
        source = viewable_run(self.games, player, game_id, self.matches)
        steps = self.engine.replay_steps(source)
        pointers = self.games.pointers(source.id)
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
                         steps=[ReplayStep(version=i, action=a, pointer=pointers.get(i)) for i, a in enumerate(steps)])


class _ChangeRun:
    def __init__(self, engine: GameEngine, games: GameRepository, locks: RunLocks, clock: Clock) -> None:
        self.engine, self.games, self.locks, self.clock = engine, games, locks, clock

    def _change(self, player: Player, game_id: str, expected_version: int | None,
                play: Callable[[Run], Outcome], debug: bool = False,
                pointer: dict[str, Any] | None = None, seat: int | None = None,
                load: Callable[[], Run] | None = None) -> ActionResult:
        """``seat``, ``load``: a coop run's player (the view is theirs) and how the run is loaded (theirs to play)."""
        with self.locks.hold(game_id):
            run = load() if load is not None else owned_run(self.games, player, game_id)
            run.check_version(expected_version)
            run.check_playable()
            outcome = play(run)
            version = run.version
            run.record(outcome.command, outcome.progress, self.clock.now(), stats=outcome.stats, debug=debug)
            if run.owned_by(player.id):  # (a coop partner's action keeps the owner's name)
                run.owner_name = player.name or run.owner_name
            self.games.save(run, expected_version=version)
            self.engine.commit(run, outcome)
            if pointer is not None and not run.replay:
                # (only for watching the run again: the action stands without it)
                try:
                    self.games.save_pointer(run.id, version, pointer)
                except Exception:
                    log.exception("the pointer of %s at version %d wasn't kept", run.id, version)
            return ActionResult(game=self.engine.view(run, seat), events=outcome.events)


class PlayAction(_ChangeRun):
    """A player action on one of their runs; a run of a match goes through the match's rules (matches.py)."""

    def __init__(self, engine: GameEngine, games: GameRepository, locks: RunLocks, clock: Clock,
                 matches: Matches | None = None) -> None:
        super().__init__(engine, games, locks, clock)
        self.matches = matches

    def __call__(self, player: Player, game_id: str, action: PlayerAction,
                 expected_version: int | None = None, pointer: dict[str, Any] | None = None) -> ActionResult:
        """``pointer``: the player's pointer before the action, kept for watching the run again."""
        run, seat = member_run(self.games, self.matches, player, game_id)
        if action.type == "continue":
            # (recorded only when continuing changes the run: otherwise the history would fill with no-ops)
            if run.finished or not self.engine.continues(run):
                return ActionResult(game=self.engine.view(run, seat), events=[])
        if seat is None:
            def act() -> ActionResult:
                return self._change(player, game_id, expected_version, lambda run: self.engine.apply(run, action),
                                    pointer=pointer)
        else:
            # coop: both players act on the run, on its latest version (their cards are theirs to name)
            def act() -> ActionResult:
                before = self.games.get(game_id).version
                result = self._change(player, game_id, None, lambda run: self.engine.apply(run, action, seat),
                                      pointer=pointer, seat=seat,
                                      load=lambda: member_run(self.games, self.matches, player, game_id)[0])
                if self.matches is not None:
                    self.matches.record_step(game_id, CoopStep(
                        version=result.game.version - 1 if result.game.version > before else before, seat=seat,
                        action=action_dict(action), events=result.events, game=result.game))
                return result
        if run.match_id is not None and self.matches is not None:
            return self.matches.play(player, run, action.type, act)
        return act()


class RunDebugCommand(_ChangeRun):
    """Test helpers (give money, add a joker, force a boss ...): on a server
    with debug commands, or for the accounts whose roles allow them (testers).
    They are recorded like actions, so the run still replays; the run then
    doesn't count for statistics."""

    def __init__(self, engine: GameEngine, games: GameRepository, locks: RunLocks, clock: Clock,
                 enabled: bool, matches: Matches | None = None) -> None:
        super().__init__(engine, games, locks, clock)
        self.enabled = enabled
        self.matches = matches

    def __call__(self, player: Player, game_id: str, command: dict[str, Any],
                 expected_version: int | None = None) -> ActionResult:
        run, seat = member_run(self.games, self.matches, player, game_id)
        # (a replay may play the debug commands of the run it copies)
        if not (self.enabled or allowed(player, Permission.DEBUG_COMMANDS)) and not run.replay:
            raise DebugCommandsDisabled()

        def act() -> ActionResult:
            return self._change(player, game_id, expected_version if seat is None else None,
                                lambda run: self.engine.apply_debug(run, command, seat), debug=True, seat=seat,
                                load=lambda: member_run(self.games, self.matches, player, game_id)[0])
        if run.match_id is not None and self.matches is not None:
            return self.matches.play(player, run, "debug", act)  # (the match catches up after it)
        return act()


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
        if record is not None and player.name and record.name != player.name:
            # (the name others see is the account's: it heals a name a coop partner's actions wrote over it)
            record = self.games.set_player(player.id, player.name)
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
    a private profile shows only the name), and their multiplayer matches."""

    def __init__(self, engine: GameEngine, games: GameRepository, clock: Clock,
                 matches: Matches | None = None) -> None:
        self.engine, self.games, self.clock, self.matches = engine, games, clock, matches

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
        multiplayer, history = None, []
        if self.matches is not None:
            played = self.matches.matches.finished_matches(player_id)
            if played:
                multiplayer = multiplayer_stats(played, player_id)
                history = [self.matches.history_entry(m, player_id) for m in played[:PROFILE_MATCHES]]
        return PlayerProfileView(
            id=player_id, name=name, you=you, private=private, stats=player_stats(runs, self.clock.now()),
            collection=self.engine.collection(self.engine.player_progress(runs)),
            runs=[summary_view(r) for r in recent], multiplayer=multiplayer, matches=history)


class GetCoopDecks:
    """A coop run's two decks (each player's cards, and those still to draw), for the players' deck views."""

    def __init__(self, engine: GameEngine, games: GameRepository, matches: Matches) -> None:
        self.engine, self.games, self.matches = engine, games, matches

    def __call__(self, player: Player, game_id: str) -> CoopDecksView:
        run, seat = member_run(self.games, self.matches, player, game_id)
        if seat is None and run.settings.mode != "coop":
            raise IllegalAction("not a coop run")
        return self.engine.coop_decks(run)


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
    game_summary: GetGameSummary
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
    create_match: CreateMatch
    join_match: JoinMatch
    get_match: GetMatch
    current_match: CurrentMatch
    change_match: ChangeMatchSettings
    start_match: StartMatch
    vote_blind: VoteBlind
    leave_match: LeaveMatch
    set_selection: SetSelection
    coop_steps: GetSteps
    coop_decks: GetCoopDecks
    rematch: Rematch
    kick_player: KickPlayer
    send_emote: SendEmote
    match_history: GetMatchHistory
    multiplayer_stats: GetMultiplayerStats


__all__ = ["Authenticate", "CreateGame", "DeleteGame", "GetCatalog", "GetGame", "GetGameSummary", "GetGlobalStats",
           "GetHistory",
           "GetLeaderboard", "GetLegalActions", "GetMe", "GetPlayerProfile", "GetPlayerStats", "ImportGame",
           "ListGames", "PlayAction", "PreviewHand", "RunDebugCommand", "UpdateMe", "UseCases", "WatchGame"]
