"""A multiplayer match: players meet in a lobby, then play their runs together.

PvP: each player plays their own run of the same seed (``GameSettings.mode``
"pvp": a lost round doesn't end the run).  The runs are ordinary runs, played
by their owners; the match keeps only what isn't in them:

- who plays (``players``, in seat order) and their runs;
- the blind votes: at each blind both players choose to play it or skip it,
  and it is skipped only when both skip it (``decision``);
- since when a player has been waiting for the other one (``waits``): when it
  is longer than the timer, the late player is moved on;
- how it ended (``winner``, ``result``).

Hit points come from the two runs (each run records the blinds it finished):
they are derived, like a run's progress, never stored.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from typing import Any

from .errors import DomainError, IllegalAction, InvalidGameSettings
from .run import GAME_SPEEDS, SEED_PATTERN

MATCH_MODES = ("pvp", "coop")
TIMERS = (60, 120, 180, 300)  # seconds a player has once the other one waits
MAX_PLAYERS = 2
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # (no 0/O, 1/I: codes are read aloud)
CODE_LENGTH = 6
BLIND_CHOICES = ("select", "skip")


class MatchNotFound(DomainError):
    code = "match_not_found"

    def __init__(self, what: str) -> None:
        super().__init__(f"no match {what!r}")


class MatchFull(DomainError):
    code = "match_full"

    def __init__(self) -> None:
        super().__init__("the match already has its players")


class MatchStarted(DomainError):
    code = "match_started"

    def __init__(self, message: str = "the match has already started") -> None:
        super().__init__(message)


class NotMatchHost(DomainError):
    code = "not_host"

    def __init__(self) -> None:
        super().__init__("only the player who made the match can do that")


class InAnotherMatch(DomainError):
    code = "in_a_match"

    def __init__(self, match_id: str) -> None:
        super().__init__("you are playing another match: leave it first")
        self.match_id = match_id


class WaitingForOpponent(IllegalAction):
    """The match waits for the other player (the run is unchanged)."""

    code = "waiting_for_opponent"


class MatchStatus(StrEnum):
    LOBBY = "lobby"  # waiting for players
    PLAYING = "playing"
    FINISHED = "finished"


@dataclass(frozen=True)
class MatchSettings:
    """What the host chooses: the deck and stake both players play, the seed
    (None: a random one, the same for both), and the timer."""

    deck: str = "b_red"
    stake: int = 1
    seed: str | None = None
    timer: int = 120

    def __post_init__(self) -> None:
        if not 1 <= self.stake <= 8:
            raise InvalidGameSettings("the stake is a level from 1 (White) to 8 (Gold)")
        if self.seed is not None and not SEED_PATTERN.match(self.seed):
            raise InvalidGameSettings("a seed is 1 to 8 letters or digits")
        if self.timer not in TIMERS:
            raise InvalidGameSettings(f"the timer is one of {', '.join(map(str, TIMERS))} seconds")


@dataclass
class MatchPlayer:
    id: str
    name: str | None = None
    game_speed: float = 1.0  # the player's game speed setting (their run's)
    run_id: str | None = None  # PvP: the player's run, once the match has started
    left: bool = False  # left the match (it is lost)

    def __post_init__(self) -> None:
        if self.game_speed not in GAME_SPEEDS:
            raise InvalidGameSettings(f"the game speed is one of {', '.join(f'{s:g}' for s in GAME_SPEEDS)}")


@dataclass(frozen=True)
class Vote:
    choice: str  # "select" or "skip"
    at: datetime


@dataclass(frozen=True)
class Wait:
    """A player waits for the other one since ``since``: ``point`` says at
    what (``round:<blind index>``: they finished the blind, ``vote:<blind
    index>``: they chose for the next blind)."""

    point: str
    since: datetime


@dataclass
class Match:
    id: str
    code: str
    mode: str
    host: str
    created_at: datetime
    updated_at: datetime
    settings: MatchSettings = field(default_factory=MatchSettings)
    players: list[MatchPlayer] = field(default_factory=list)  # in seat order
    status: MatchStatus = MatchStatus.LOBBY
    seed: str | None = None  # the seed the runs are played with (once started)
    votes: dict[int, dict[int, Vote]] = field(default_factory=dict)  # blind index -> seat -> vote
    waits: dict[int, Wait] = field(default_factory=dict)  # seat -> since when they wait
    winner: int | None = None  # the winner's seat (None: a draw, or not over)
    result: str | None = None  # how it ended: "hp", "left", "game_over"
    finished_at: datetime | None = None
    version: int = 0  # the number of times it was saved (optimistic saves)

    def __post_init__(self) -> None:
        if self.mode not in MATCH_MODES:
            raise InvalidGameSettings(f"the mode is one of {', '.join(MATCH_MODES)}")

    # ------------------------------------------------------------ players
    def seat_of(self, player_id: str) -> int | None:
        return next((i for i, p in enumerate(self.players) if p.id == player_id), None)

    def member(self, player_id: str) -> int:
        """The player's seat; not a player of this match: it isn't found."""
        seat = self.seat_of(player_id)
        if seat is None:
            raise MatchNotFound(self.id)
        return seat

    @property
    def active(self) -> bool:
        return self.status is not MatchStatus.FINISHED

    def join(self, player: MatchPlayer, at: datetime) -> int:
        seat = self.seat_of(player.id)
        if seat is not None:
            self.players[seat] = replace(self.players[seat], name=player.name or self.players[seat].name,
                                         game_speed=player.game_speed)
            return seat
        if self.status is not MatchStatus.LOBBY:
            raise MatchStarted()
        if len(self.players) >= MAX_PLAYERS:
            raise MatchFull()
        self.players.append(player)
        self.updated_at = at
        return len(self.players) - 1

    def leave(self, player_id: str, at: datetime) -> None:
        """In the lobby: out of it (the host closes it); playing: the match is lost."""
        seat = self.member(player_id)
        self.updated_at = at
        if self.status is MatchStatus.LOBBY:
            if player_id == self.host:
                self.finish(None, "closed", at)
            else:
                del self.players[seat]
            return
        if self.status is MatchStatus.PLAYING:
            self.players[seat].left = True
            others = [i for i, p in enumerate(self.players) if not p.left]
            self.finish(others[0] if len(others) == 1 else None, "left", at)

    def check_host(self, player_id: str) -> None:
        if player_id != self.host:
            raise NotMatchHost()

    def change_settings(self, settings: MatchSettings, at: datetime) -> None:
        if self.status is not MatchStatus.LOBBY:
            raise MatchStarted()
        self.settings = settings
        self.updated_at = at

    def start(self, seed: str, run_ids: list[str], at: datetime) -> None:
        if self.status is not MatchStatus.LOBBY:
            raise MatchStarted()
        if len(self.players) < MAX_PLAYERS or len(run_ids) != len(self.players):
            raise IllegalAction("the match needs two players")
        self.seed = seed
        for p, run_id in zip(self.players, run_ids, strict=True):
            p.run_id = run_id
        self.status = MatchStatus.PLAYING
        self.updated_at = at

    def finish(self, winner: int | None, result: str, at: datetime) -> None:
        if self.status is MatchStatus.FINISHED:
            return
        self.status = MatchStatus.FINISHED
        self.winner = winner
        self.result = result
        self.finished_at = at
        self.updated_at = at
        self.waits.clear()

    # ------------------------------------------------------------ blinds
    def vote(self, seat: int, index: int, choice: str, at: datetime) -> None:
        """The player's choice for the blind ``index`` (the blinds the run has
        finished): it can change until the other player has chosen too."""
        if choice not in BLIND_CHOICES:
            raise IllegalAction(f"choose {' or '.join(BLIND_CHOICES)}")
        if self.status is not MatchStatus.PLAYING:
            raise IllegalAction("the match isn't being played")
        votes = self.votes.setdefault(index, {})
        if self.decision(index) is not None:
            raise IllegalAction("both players have chosen already")
        votes[seat] = Vote(choice, at)
        self.updated_at = at

    def decision(self, index: int) -> str | None:
        """What both players do at blind ``index``: "skip" only if both skip it;
        None until both have chosen."""
        votes = self.votes.get(index, {})
        if len(votes) < len(self.players):
            return None
        return "skip" if all(v.choice == "skip" for v in votes.values()) else "select"

    # ------------------------------------------------------------ waiting
    def set_wait(self, seat: int, point: str | None, at: datetime) -> bool:
        """The player waits at ``point`` (None: doesn't wait); True if that changed."""
        old = self.waits.get(seat)
        if point is None:
            if old is None:
                return False
            del self.waits[seat]
            return True
        if old is not None and old.point == point:
            return False
        self.waits[seat] = Wait(point, at)
        return True

    # ------------------------------------------------------------ storage
    def to_doc(self) -> dict[str, Any]:
        """The match as JSON (what a repository stores)."""
        s = self.settings
        return {
            "settings": {"deck": s.deck, "stake": s.stake, "seed": s.seed, "timer": s.timer},
            "players": [{"id": p.id, "name": p.name, "game_speed": p.game_speed, "run_id": p.run_id,
                         "left": p.left} for p in self.players],
            "seed": self.seed,
            "votes": {str(i): {str(seat): {"choice": v.choice, "at": v.at.isoformat()} for seat, v in vs.items()}
                      for i, vs in self.votes.items()},
            "waits": {str(seat): {"point": w.point, "since": w.since.isoformat()} for seat, w in self.waits.items()},
            "winner": self.winner, "result": self.result,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }

    @classmethod
    def from_doc(cls, *, id: str, code: str, mode: str, host: str, status: str, created_at: datetime,
                 updated_at: datetime, version: int, doc: dict[str, Any]) -> Match:
        s = doc.get("settings") or {}
        return cls(
            id=id, code=code, mode=mode, host=host, created_at=created_at, updated_at=updated_at,
            settings=MatchSettings(deck=s.get("deck", "b_red"), stake=s.get("stake", 1), seed=s.get("seed"),
                                   timer=s.get("timer", 120)),
            players=[MatchPlayer(id=p["id"], name=p.get("name"), game_speed=p.get("game_speed", 1.0),
                                 run_id=p.get("run_id"), left=bool(p.get("left"))) for p in doc.get("players", [])],
            status=MatchStatus(status), seed=doc.get("seed"),
            votes={int(i): {int(seat): Vote(v["choice"], datetime.fromisoformat(v["at"])) for seat, v in vs.items()}
                   for i, vs in (doc.get("votes") or {}).items()},
            waits={int(seat): Wait(w["point"], datetime.fromisoformat(w["since"]))
                   for seat, w in (doc.get("waits") or {}).items()},
            winner=doc.get("winner"), result=doc.get("result"),
            finished_at=datetime.fromisoformat(doc["finished_at"]) if doc.get("finished_at") else None,
            version=version)
