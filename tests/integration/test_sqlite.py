from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from balatro_api.domain import (
    ANONYMOUS_PLAYER,
    Command,
    GameNotFound,
    GameSettings,
    Phase,
    Progress,
    Run,
    VersionConflict,
)
from balatro_api.infrastructure.persistence import InMemoryGameRepository, SqliteGameRepository
from balatro_api.infrastructure.persistence.sqlite import SCHEMA

T0 = datetime(2026, 1, 1, tzinfo=UTC)
P = Progress(phase=Phase.BLIND_SELECT, ante=1, round=0, dollars=4, won=False)


@pytest.fixture(params=["sqlite", "memory"])
def repo(request, tmp_path):
    if request.param == "memory":
        yield InMemoryGameRepository()
    else:
        r = SqliteGameRepository(tmp_path / "runs.db")
        yield r
        r.close()


def make(run_id: str, at: datetime = T0, owner: str = "p1") -> Run:
    return Run(id=run_id, settings=GameSettings(seed="ABC", deck="b_blue", stake=3, challenge=None, game_speed=2),
               engine_version="0.3.0", progress=P, created_at=at, updated_at=at, owner=owner)


def test_round_trip(repo):
    run = make("a")
    repo.add(run)
    later = T0 + timedelta(minutes=1)
    run.record(Command({"cmd": "select_blind"}), Progress(Phase.PLAYING, 1, 1, 4, False), later)
    run.record(Command({"cmd": "play", "cards": [0, 2]}), Progress(Phase.PLAYING, 1, 1, 7.5, False), later)
    repo.save(run, expected_version=0)
    got = repo.get("a")
    assert got == run
    assert got.commands[1].as_dict() == {"cmd": "play", "cards": [0, 2]}


def test_optimistic_concurrency(repo):
    run = make("a")
    repo.add(run)
    first, second = repo.get("a"), repo.get("a")
    first.record(Command({"cmd": "select_blind"}), P, T0)
    repo.save(first, expected_version=0)
    second.record(Command({"cmd": "skip_blind"}), P, T0)
    with pytest.raises(VersionConflict):
        repo.save(second, expected_version=0)
    assert [c.as_dict() for c in repo.get("a").commands] == [{"cmd": "select_blind"}]


def test_list_and_delete(repo):
    for i in range(3):
        repo.add(make(f"r{i}", T0 + timedelta(minutes=i)))
    repo.add(make("theirs", T0 + timedelta(minutes=5), owner="p2"))
    assert [s.id for s in repo.list("p1", 10, 0)] == ["r2", "r1", "r0"]
    assert [s.id for s in repo.list("p1", 1, 1)] == ["r1"]
    assert [(s.id, s.owner) for s in repo.list("p2", 10, 0)] == [("theirs", "p2")]
    repo.delete("r1")
    with pytest.raises(GameNotFound):
        repo.get("r1")
    with pytest.raises(GameNotFound):
        repo.delete("r1")
    with pytest.raises(GameNotFound):
        repo.save(make("r1"), expected_version=0)


def test_sqlite_survives_a_restart(tmp_path):
    path = tmp_path / "runs.db"
    r = SqliteGameRepository(path)
    run = make("a")
    r.add(run)
    run.record(Command({"cmd": "select_blind"}), P, T0)
    r.save(run, expected_version=0)
    r.close()
    assert SqliteGameRepository(path).get("a") == run


def test_sqlite_gives_old_runs_to_the_anonymous_player(tmp_path):
    """A database from before runs had owners."""
    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.executescript(SCHEMA.replace(",\n    owner TEXT NOT NULL", ""))
    db.execute("INSERT INTO runs VALUES ('old', 'ABC', 'b_red', 1, NULL, 1.0, '0.3.0', 0, 'blind_select', 1, 0, 4, 0, "
               "'2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')")
    db.commit()
    db.close()
    repo = SqliteGameRepository(path)
    assert repo.get("old").owner == ANONYMOUS_PLAYER
    assert [s.id for s in repo.list(ANONYMOUS_PLAYER, 10, 0)] == ["old"]
    repo.add(make("new"))
    assert repo.get("new").owner == "p1"
