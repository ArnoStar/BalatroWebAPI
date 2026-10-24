"""What the use cases need from the outside world.  The infrastructure layer
implements these; the use cases only see the protocols."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from balatro_api.domain import Command, GameSettings, Progress, Run, RunSummary

from .dto import Catalog, FeedbackEvent, GameView, HandPreview, LegalAction, Player, PlayerAction


@dataclass(frozen=True)
class Outcome:
    """An action the engine accepted, not yet part of the run: ``command`` is
    what to record, ``state`` the engine's game after it (opaque to the
    application; hand it back with :meth:`GameEngine.commit` once the run is
    saved)."""

    command: Command
    progress: Progress
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

    def start(self, run_id: str, settings: GameSettings) -> Progress: ...

    def view(self, run: Run) -> GameView: ...

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

    def forget(self, run_id: str) -> None: ...

    def catalog(self) -> Catalog: ...


class GameRepository(Protocol):
    def add(self, run: Run) -> None: ...

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
