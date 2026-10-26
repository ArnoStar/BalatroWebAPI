"""A run: its settings and the commands the player made, in order.

The game is deterministic: the same settings and the same commands always
give the same game.  So the command history *is* the game; everything else
(the cards, the shop, the score) is derived from it by the engine.  The
domain only enforces what is true of every run: commands are appended one
at a time, the version is the number of commands, nothing happens after the
run is over, and a client must act on the current version.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from .errors import GameOver, InvalidGameSettings, VersionConflict
from .stats import RunStats

GAME_SPEEDS = (0.5, 1.0, 2.0, 4.0)
# who owns the runs when the server runs without sign-in (and the runs made
# before runs had owners)
ANONYMOUS_PLAYER = "local"
SEED_PATTERN = re.compile(r"^[A-Za-z0-9]{1,8}$")


@dataclass(frozen=True)
class GameSettings:
    """What a run is started with.  ``game_speed`` is the game's speed
    setting: it changes when animated effects land, which decides a few races
    (as in the game), so it is part of the run.  ``seeded``: the player chose
    the seed (as in the game, such a run doesn't count for statistics)."""

    seed: str
    deck: str = "b_red"
    stake: int = 1
    challenge: str | None = None
    game_speed: float = 1.0
    seeded: bool = False

    def __post_init__(self) -> None:
        if not SEED_PATTERN.match(self.seed):
            raise InvalidGameSettings("a seed is 1 to 8 letters or digits")
        if not 1 <= self.stake <= 8:
            raise InvalidGameSettings("the stake is a level from 1 (White) to 8 (Gold)")
        if self.game_speed not in GAME_SPEEDS:
            raise InvalidGameSettings(f"the game speed is one of {', '.join(f'{s:g}' for s in GAME_SPEEDS)}")


class Phase(StrEnum):
    """Which screen the run is on, i.e. what kind of decision it waits for."""

    BLIND_SELECT = "blind_select"
    PLAYING = "playing"
    ROUND_EVAL = "round_eval"
    SHOP = "shop"
    PACK = "pack"
    GAME_OVER = "game_over"


@dataclass(frozen=True)
class Progress:
    """Where a run stands; kept with it so runs can be listed without replaying them."""

    phase: Phase
    ante: int
    round: int
    dollars: float
    won: bool

    @property
    def over(self) -> bool:
        return self.phase is Phase.GAME_OVER


@dataclass(frozen=True)
class Command:
    """One accepted command, in the engine's own format (opaque here)."""

    payload: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return dict(self.payload)


@dataclass(frozen=True)
class RunSummary:
    id: str
    settings: GameSettings
    progress: Progress
    version: int
    created_at: datetime
    updated_at: datetime
    owner: str = ANONYMOUS_PLAYER
    stats: RunStats = field(default_factory=RunStats)
    debug: bool = False
    replay: bool = False
    tracks_progress: bool = False

    @property
    def counts(self) -> bool:
        return counts(self.settings, self.debug)

    @property
    def finished(self) -> bool:
        return finished(self.progress)


def finished(progress: Progress) -> bool:
    """The run is over (lost, or won: what comes after the win is endless play)."""
    return progress.phase is Phase.GAME_OVER or progress.won


def counts(settings: GameSettings, debug: bool) -> bool:
    """Whether a run counts for statistics and leaderboards: as in the game,
    not when the player chose the seed or plays a challenge; nor when a debug
    command was used."""
    return not settings.seeded and settings.challenge is None and not debug


@dataclass
class Run:
    id: str
    settings: GameSettings
    engine_version: str
    progress: Progress
    created_at: datetime
    updated_at: datetime
    commands: list[Command] = field(default_factory=list)
    owner: str = ANONYMOUS_PLAYER
    """The player whose run it is (their account id at the identity service).
    Nobody else can play it; others may watch it once it is finished, unless
    the owner's profile is private."""
    owner_name: str | None = None
    """The owner's display name when they last played it (for leaderboards)."""
    stats: RunStats = field(default_factory=RunStats)
    """What the run added to the player's statistics (derived, like ``progress``)."""
    debug: bool = False
    """A debug command was used: the run doesn't count for statistics."""
    replay: bool = False
    """Rebuilt from another run's history (a bug report, or watching a run):
    the caller plays it, but it isn't one of their runs (not listed)."""
    start_profile: dict[str, Any] | None = None
    """The player's progress when the run started (what was unlocked and
    discovered, as the engine's Profile JSON): it decides the pools, so it is
    part of the run like its settings.  None: a run from before progress was
    kept, played fully unlocked.  {"all": true}: played fully unlocked (a tester's
    choice)."""

    @property
    def tracks_progress(self) -> bool:
        """The run started from the player's real progress, so it adds to it."""
        return self.start_profile is not None and not self.start_profile.get("all") and not self.replay

    @property
    def finished(self) -> bool:
        return finished(self.progress)

    @property
    def version(self) -> int:
        """The number of accepted commands: every command makes a new version."""
        return len(self.commands)

    def check_version(self, expected: int | None) -> None:
        if expected is not None and expected != self.version:
            raise VersionConflict(expected, self.version)

    def owned_by(self, player_id: str) -> bool:
        return self.owner == player_id

    def check_playable(self) -> None:
        if self.progress.over:
            raise GameOver()

    @property
    def counts(self) -> bool:
        return counts(self.settings, self.debug)

    def record(self, command: Command, progress: Progress, at: datetime, stats: RunStats | None = None,
               debug: bool = False) -> None:
        self.check_playable()
        self.commands.append(command)
        self.progress = progress
        self.updated_at = at
        if stats is not None:
            self.stats = stats
        self.debug = self.debug or debug

    def summary(self) -> RunSummary:
        return RunSummary(self.id, self.settings, self.progress, self.version, self.created_at, self.updated_at,
                          self.owner, self.stats, self.debug, self.replay, self.tracks_progress)
