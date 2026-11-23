"""What the use cases need from the outside world.  The infrastructure layer
implements these; the use cases only see the protocols."""

from __future__ import annotations

import builtins
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from balatro_api.domain import (
    Command,
    GameSettings,
    Match,
    ModRecord,
    ModVersion,
    Phase,
    Progress,
    Run,
    RunStats,
    RunSummary,
)

from .dto import (
    Catalog,
    CollectionView,
    CoopDecksView,
    CreativeCommand,
    FeedbackEvent,
    GameView,
    GlobalStats,
    HandPreview,
    LeaderboardName,
    LegalAction,
    OpponentView,
    Player,
    PlayerAction,
    ProgressView,
)


@dataclass(frozen=True)
class Outcome:
    """An action the engine accepted, not yet part of the run: ``command`` is
    what to record, ``state`` the engine's game after it (opaque to the
    application; hand it back with :meth:`GameEngine.commit` once the run is
    saved)."""

    command: Command
    progress: Progress
    stats: RunStats
    events: list[FeedbackEvent]
    state: object


@dataclass(frozen=True)
class MatchRecord:
    """What a match needs to know of a run: the blinds it has finished (the
    engine's PvP records: ante, slot, chips, target, lost, skipped), where it
    stands, and whether the blind on deck can be skipped."""

    blinds: list[dict[str, Any]]
    phase: Phase
    game_over: bool
    can_skip: bool
    version: int


@dataclass(frozen=True)
class PvPState:
    """The engine's PvP rules applied to both runs (see balatro.mods.pvp.match_state)."""

    hp: list[int]
    rounds: list[dict[str, Any]]
    over: bool
    winner: int | None
    start_hp: int
    safe_antes: int
    loss_damage: int


class GameEngine(Protocol):
    """The game rules.  Every method gives the same answer for the same run
    (settings + commands); none of them changes a run."""

    @property
    def version(self) -> str: ...

    def random_seed(self) -> str: ...

    def latest_mode_rules(self, mode: str) -> int | None:
        """The version of a multiplayer mode's rules a new run is played with (``GameSettings.mode_rules``);
        None: the mode has one."""
        ...

    def check_settings(self, settings: GameSettings,
                       mod_packages: dict[str, dict[str, Any]] | None = None) -> GameSettings:
        """The settings the game will actually use (seed as the game reads
        it, a challenge's own deck and stake).  Raises InvalidGameSettings, or
        InvalidMod when the run's mods can't be played together."""
        ...

    def start(self, run_id: str, settings: GameSettings, start_profile: dict[str, Any] | None = None,
              mod_packages: dict[str, dict[str, Any]] | None = None) -> Progress:
        """A new run's game, from the player's progress (None: fully unlocked, as runs were before progress)
        and with its mods' packages (``settings.mods``, by hash)."""
        ...

    def check_mod(self, package: dict[str, Any]) -> list[str]:
        """What is wrong with a mod's package (empty: it can be played): the format, then a short
        run played with it."""
        ...

    def mod_summary(self, package: dict[str, Any]) -> dict[str, Any]:
        """How many items of each kind the package has, its rules, whether it is creative mode."""
        ...

    def official_mods(self) -> list[dict[str, Any]]:
        """The mods that come with the engine (the examples)."""
        ...

    def apply_creative(self, run: Run, command: CreativeCommand) -> Outcome:
        """A creative mode change (a run with a creative mod), played like an action."""
        ...

    def view(self, run: Run, seat: int | None = None) -> GameView:
        """``seat``: a coop run's player (the legal actions are theirs)."""
        ...

    def run_stats(self, run: Run) -> RunStats:
        """What the run has added to the player's statistics so far."""
        ...

    def load(self, run: Run) -> tuple[Progress, RunStats]:
        """Replay a run's commands (a run rebuilt from its history).  Raises
        IllegalAction naming the first command that doesn't replay."""
        ...

    def legal_actions(self, run: Run, seat: int | None = None) -> list[LegalAction]: ...

    def apply(self, run: Run, action: PlayerAction, seat: int | None = None) -> Outcome:
        """Play the action on a copy of the run's game (``seat``: a coop run's player making it).  Raises
        IllegalAction (the run is unchanged)."""
        ...

    def apply_debug(self, run: Run, command: dict[str, Any], seat: int | None = None) -> Outcome:
        """A test helper command (add a joker, set the money ...)."""
        ...

    def commit(self, run: Run, outcome: Outcome) -> None:
        """The run now includes the outcome's command: keep its game."""
        ...

    def preview_hand(self, run: Run, cards: Sequence[int]) -> HandPreview: ...

    def continues(self, run: Run) -> bool:
        """Whether continuing the run from the main menu changes it."""
        ...

    def replay_steps(self, run: Run) -> list[dict[str, Any]]:
        """The run's commands as player actions (cards by id), to play them again on a copy."""
        ...

    def player_progress(self, runs: Sequence[RunSummary]) -> dict[str, Any]:
        """The progress the player's runs add up to (an engine profile, as JSON: what a new run starts from)."""
        ...

    def check_unlocked(self, settings: GameSettings, profile: dict[str, Any]) -> None:
        """Raises Locked if the run setup wouldn't offer these settings with this progress."""
        ...

    def progress_view(self, profile: dict[str, Any], all_unlocked: bool, can_unlock_all: bool) -> ProgressView: ...

    def collection(self, profile: dict[str, Any]) -> CollectionView: ...

    def forget(self, run_id: str) -> None: ...

    def catalog(self) -> Catalog: ...

    # ---------------------------------------------------------- multiplayer
    def apply_command(self, run: Run, command: dict[str, Any]) -> Outcome:
        """An engine command the match plays for the player (a blind both chose, the timer's move)."""
        ...

    def match_record(self, run: Run) -> MatchRecord: ...

    def timeout_command(self, run: Run) -> dict[str, Any] | None:
        """The command that moves a late player on (None at the blind select, which the match decides)."""
        ...

    def pvp_state(self, blinds: Sequence[list[dict[str, Any]]], eliminated: Sequence[bool]) -> PvPState: ...

    def coop_state(self, run: Run) -> dict[str, Any] | None:
        """A coop run's turn, joker slots, shop votes and seats (and whether it is over); None for another run."""
        ...

    def opponent_view(self, run: Run) -> OpponentView:
        """The public part of a run, as the other player of a match sees it."""
        ...

    def coop_decks(self, run: Run) -> CoopDecksView:
        """A coop run's two decks (each player's cards, and those still to draw: never their order)."""
        ...


@dataclass(frozen=True)
class PlayerRecord:
    """What this API keeps about a player: their name when they last played, and their settings."""

    id: str
    name: str | None = None
    private: bool = False
    all_unlocked: bool = False


class GameRepository(Protocol):
    def add(self, run: Run) -> None: ...

    def player(self, player_id: str) -> PlayerRecord | None:
        """None: the API has never seen this player."""
        ...

    def set_player(self, player_id: str, name: str | None, *, private: bool | None = None,
                   all_unlocked: bool | None = None) -> PlayerRecord:
        """Change the player's settings (None: keep), creating the record if needed."""
        ...

    def get(self, run_id: str) -> Run:
        """Raises GameNotFound."""
        ...

    def save(self, run: Run, expected_version: int) -> None:
        """Store the run's new commands.  Raises VersionConflict when the
        stored run is not at ``expected_version`` (someone else acted)."""
        ...

    def delete(self, run_id: str) -> None:
        """Raises GameNotFound."""
        ...

    def list(self, owner: str, limit: int, offset: int) -> list[RunSummary]:
        """The owner's runs, most recently updated first."""
        ...

    def runs_of(self, owner: str) -> builtins.list[RunSummary]:
        """All the owner's runs (with their stats), least recently updated first."""
        ...

    def save_pointer(self, run_id: str, version: int, pointer: dict[str, Any]) -> None:
        """Keep the player's pointer before the action played at ``version`` (for watching the run
        again). Not part of the run: an action stands without it."""
        ...

    def pointers(self, run_id: str) -> dict[int, dict[str, Any]]:
        """The pointers kept for the run, by the version of their action."""
        ...

    def leaderboard(self, board: LeaderboardName, deck: str | None, stake: int | None, limit: int,
                    owner: str) -> BoardPage:
        """Each player's best counted run on the board (for "wins": their
        number of won counted runs), best first; equal values by who got
        there first.  The top ``limit`` rows, plus ``owner``'s row."""
        ...

    def global_stats(self) -> GlobalStats:
        """Everyone's counted runs together."""
        ...


class MatchRepository(Protocol):
    def add_match(self, match: Match) -> None: ...

    def get_match(self, match_id: str) -> Match:
        """Raises MatchNotFound."""
        ...

    def match_by_code(self, code: str) -> Match:
        """The match in its lobby with this invite code. Raises MatchNotFound."""
        ...

    def current_match(self, player_id: str) -> Match | None:
        """The player's latest match not finished (in its lobby, or being played)."""
        ...

    def save_match(self, match: Match, expected_version: int) -> None:
        """Store the match (its version + 1).  Raises VersionConflict when the
        stored match is not at ``expected_version``."""
        ...

    def finished_matches(self, player_id: str, limit: int | None = None,
                         before: datetime | None = None) -> list[Match]:
        """The player's finished matches (not lobbies closed before starting), the latest first
        (by ``updated_at``), only those before ``before`` if given."""
        ...


@dataclass(frozen=True)
class BoardRow:
    rank: int  # tied values share a rank
    owner: str
    name: str | None  # the owner's display name
    value: float
    deck: str | None
    stake: int | None
    won: bool | None
    at: datetime


@dataclass(frozen=True)
class BoardPage:
    rows: list[BoardRow]
    players: int


class Authenticator(Protocol):
    """Checks the access tokens of the identity service (BalatroIndentityService)."""

    @property
    def required(self) -> bool:
        """False when the server runs without sign-in: every caller is the
        anonymous player."""
        ...

    def authenticate(self, token: str | None) -> Player:
        """The token's player. Raises NotAuthenticated, or AuthUnavailable when
        the identity service's keys can't be fetched."""
        ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdGenerator(Protocol):
    def new_id(self) -> str: ...


class ModRepository(Protocol):
    """Mod packages, kept by content hash for good (runs replay with them), and the registry of
    published mods."""

    def put_package(self, hash: str, package: dict[str, Any], at: datetime) -> None:
        """Keep a package (nothing happens if it is there already)."""
        ...

    def package(self, hash: str) -> dict[str, Any] | None: ...

    def logic(self, hashes: Sequence[str]) -> dict[str, dict[str, Any]]:
        """The packages without their images, by hash."""
        ...

    def get_mod(self, mod_id: str) -> ModRecord | None: ...

    def save_mod(self, record: ModRecord) -> None:
        """Add or replace a mod of the registry."""
        ...

    def add_version(self, version: ModVersion) -> None: ...

    def versions(self, mod_id: str) -> builtins.list[ModVersion]:
        """Newest first."""
        ...

    def find_mods(self, query: str | None, tag: str | None, sort: str, limit: int, offset: int,
                  owner: str | None = None) -> tuple[builtins.list[ModRecord], int]:
        """Listed mods matching the query (in the id, name or description) and tag, and how many match."""
        ...

    def add_install(self, mod_id: str, player_id: str, at: datetime) -> int:
        """Count the player among the mod's installs (once); its install count."""
        ...
