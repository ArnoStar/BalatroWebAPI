"""What the use cases need from the outside world.  The infrastructure layer
implements these; the use cases only see the protocols."""

from __future__ import annotations

import builtins
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from balatro_api.domain import Command, GameSettings, Progress, Run, RunStats, RunSummary

from .dto import (
    Catalog,
    CollectionView,
    FeedbackEvent,
    GameView,
    GlobalStats,
    HandPreview,
    LeaderboardName,
    LegalAction,
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


class GameEngine(Protocol):
    """The game rules.  Every method gives the same answer for the same run
    (settings + commands); none of them changes a run."""

    @property
    def version(self) -> str: ...

    def random_seed(self) -> str: ...

    def check_settings(self, settings: GameSettings) -> GameSettings:
        """The settings the game will actually use (seed as the game reads
        it, a challenge's own deck and stake).  Raises InvalidGameSettings."""
        ...

    def start(self, run_id: str, settings: GameSettings, start_profile: dict[str, Any] | None = None) -> Progress:
        """A new run's game, from the player's progress (None: fully unlocked, as runs were before progress)."""
        ...

    def view(self, run: Run) -> GameView: ...

    def run_stats(self, run: Run) -> RunStats:
        """What the run has added to the player's statistics so far."""
        ...

    def load(self, run: Run) -> tuple[Progress, RunStats]:
        """Replay a run's commands (a run rebuilt from its history).  Raises
        IllegalAction naming the first command that doesn't replay."""
        ...

    def legal_actions(self, run: Run) -> list[LegalAction]: ...

    def apply(self, run: Run, action: PlayerAction) -> Outcome:
        """Play the action on a copy of the run's game.  Raises IllegalAction
        (the run is unchanged)."""
        ...

    def apply_debug(self, run: Run, command: dict[str, Any]) -> Outcome:
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

    def leaderboard(self, board: LeaderboardName, deck: str | None, stake: int | None, limit: int,
                    owner: str) -> BoardPage:
        """Each player's best counted run on the board (for "wins": their
        number of won counted runs), best first; equal values by who got
        there first.  The top ``limit`` rows, plus ``owner``'s row."""
        ...

    def global_stats(self) -> GlobalStats:
        """Everyone's counted runs together."""
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
