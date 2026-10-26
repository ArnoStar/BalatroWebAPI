"""The use cases with a fake engine: the run only changes when everything succeeded."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from balatro_api.application.dto import NewGame, Player, PlayerAction
from balatro_api.application.errors import DebugCommandsDisabled
from balatro_api.application.locks import RunLocks
from balatro_api.application.ports import Outcome
from balatro_api.application.use_cases import CreateGame, DeleteGame, PlayAction, RunDebugCommand
from balatro_api.domain import (
    Command,
    GameNotFound,
    GameOver,
    GameSettings,
    IllegalAction,
    Locked,
    Phase,
    Progress,
    Run,
    RunStats,
    VersionConflict,
)
from balatro_api.infrastructure.persistence import InMemoryGameRepository

START = Progress(phase=Phase.BLIND_SELECT, ante=1, round=0, dollars=4, won=False)
ME = Player(id="me")
OTHER = Player(id="someone else")


class FakeEngine:
    version = "test"

    def __init__(self) -> None:
        self.committed: list[tuple[str, int]] = []
        self.forgotten: list[str] = []
        self.fail: Exception | None = None
        self.next_phase = Phase.PLAYING
        self.stats = RunStats()

    def random_seed(self) -> str:
        return "RANDOM12"

    def check_settings(self, settings: GameSettings) -> GameSettings:
        return settings

    def start(self, run_id: str, settings: GameSettings, start_profile: dict[str, Any] | None = None) -> Progress:
        return START

    def player_progress(self, runs: Any) -> dict[str, Any]:
        return {"unlocked": []}

    def check_unlocked(self, settings: GameSettings, profile: dict[str, Any]) -> None:
        if settings.deck == "b_locked":
            raise Locked("locked")

    def continues(self, run: Run) -> bool:
        return False

    def run_stats(self, run: Run) -> RunStats:
        return RunStats(most_money=4)

    def view(self, run: Run) -> Any:
        return {"id": run.id, "version": run.version}

    def apply(self, run: Run, action: PlayerAction) -> Outcome:
        if self.fail:
            raise self.fail
        return Outcome(Command({"cmd": action.type}), Progress(self.next_phase, 1, 1, 4, False), self.stats, [],
                       object())

    def apply_debug(self, run: Run, command: dict[str, Any]) -> Outcome:
        return Outcome(Command(command), START, RunStats(), [], object())

    def commit(self, run: Run, outcome: Outcome) -> None:
        self.committed.append((run.id, run.version))

    def forget(self, run_id: str) -> None:
        self.forgotten.append(run_id)


class Clock:
    def now(self) -> datetime:
        return datetime(2026, 1, 1, tzinfo=UTC)


class Ids:
    def __init__(self) -> None:
        self.n = 0

    def new_id(self) -> str:
        self.n += 1
        return f"g{self.n}"


@pytest.fixture
def setup() -> tuple[FakeEngine, InMemoryGameRepository, CreateGame, PlayAction]:
    engine, repo, locks = FakeEngine(), InMemoryGameRepository(), RunLocks()
    return (engine, repo, CreateGame(engine, repo, Ids(), Clock()),  # type: ignore[arg-type]
            PlayAction(engine, repo, locks, Clock()))  # type: ignore[arg-type]


def test_create_uses_a_random_seed_when_none_is_given(setup):
    engine, repo, create, _ = setup
    create(ME, NewGame())
    assert repo.get("g1").settings.seed == "RANDOM12"
    create(ME, NewGame(seed="ABC"))
    assert repo.get("g2").settings.seed == "ABC"


def test_an_action_is_recorded_saved_then_committed(setup):
    engine, repo, create, play = setup
    create(ME, NewGame(seed="ABC"))
    result = play(ME, "g1", PlayerAction(type="select_blind"), expected_version=0)
    assert result.game == {"id": "g1", "version": 1}
    run = repo.get("g1")
    assert [c.as_dict() for c in run.commands] == [{"cmd": "select_blind"}]
    assert run.progress.phase is Phase.PLAYING
    assert engine.committed == [("g1", 1)]


@pytest.mark.parametrize("error", [IllegalAction("no"), RuntimeError("engine bug")])
def test_a_failed_action_changes_nothing(setup, error):
    engine, repo, create, play = setup
    create(ME, NewGame(seed="ABC"))
    engine.fail = error
    with pytest.raises(type(error)):
        play(ME, "g1", PlayerAction(type="select_blind"))
    assert repo.get("g1").version == 0 and engine.committed == []


def test_a_stale_version_is_refused(setup):
    engine, repo, create, play = setup
    create(ME, NewGame(seed="ABC"))
    play(ME, "g1", PlayerAction(type="select_blind"))
    with pytest.raises(VersionConflict):
        play(ME, "g1", PlayerAction(type="play"), expected_version=0)
    assert repo.get("g1").version == 1


def test_a_concurrent_save_is_refused(setup):
    engine, repo, create, play = setup
    create(ME, NewGame(seed="ABC"))
    other = repo.get("g1")  # another server process acts first
    other.record(Command({"cmd": "skip_blind"}), START, Clock().now())
    repo.save(other, expected_version=0)
    stale = repo.get

    def get_stale(run_id: str) -> Run:
        run = stale(run_id)
        run.commands = run.commands[:0]  # this process still sees version 0
        return run
    repo.get = get_stale  # type: ignore[method-assign]
    with pytest.raises(VersionConflict):
        play(ME, "g1", PlayerAction(type="select_blind"))
    assert engine.committed == []


def test_no_action_after_game_over(setup):
    engine, repo, create, play = setup
    create(ME, NewGame(seed="ABC"))
    engine.next_phase = Phase.GAME_OVER
    play(ME, "g1", PlayerAction(type="play"))
    with pytest.raises(GameOver):
        play(ME, "g1", PlayerAction(type="play"))


def test_unknown_games(setup):
    _, _, _, play = setup
    with pytest.raises(GameNotFound):
        play(ME, "nope", PlayerAction(type="play"))


def test_delete_forgets_the_engine_game(setup):
    engine, repo, create, _ = setup
    create(ME, NewGame(seed="ABC"))
    DeleteGame(engine, repo, RunLocks())(ME, "g1")  # type: ignore[arg-type]
    assert engine.forgotten == ["g1"]
    with pytest.raises(GameNotFound):
        repo.get("g1")


def test_debug_commands_can_be_disabled(setup):
    engine, repo, create, _ = setup
    create(ME, NewGame(seed="ABC"))
    debug = RunDebugCommand(engine, repo, RunLocks(), Clock(), enabled=False)  # type: ignore[arg-type]
    with pytest.raises(DebugCommandsDisabled):
        debug(ME, "g1", {"cmd": "cheat", "dollars": 100})


def test_other_players_runs_are_not_found(setup):
    engine, repo, create, play = setup
    create(ME, NewGame(seed="ABC"))
    assert repo.get("g1").owner == "me"
    with pytest.raises(GameNotFound):
        play(OTHER, "g1", PlayerAction(type="select_blind"))
    with pytest.raises(GameNotFound):
        DeleteGame(engine, repo, RunLocks())(OTHER, "g1")  # type: ignore[arg-type]
    assert repo.get("g1").version == 0 and engine.committed == []
