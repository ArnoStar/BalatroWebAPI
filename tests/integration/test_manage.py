"""The maintenance commands: copying the old SQLite runs, rebuilding stats."""

from __future__ import annotations

import json
import sqlite3

from balatro_api.domain import ANONYMOUS_PLAYER, RunStats
from balatro_api.infrastructure.engine import BalatroEngine
from balatro_api.manage import import_sqlite, rebuild_stats

# the SQLite database of the API before PostgreSQL
OLD_SCHEMA = """
CREATE TABLE runs (
    id TEXT PRIMARY KEY, seed TEXT NOT NULL, deck TEXT NOT NULL, stake INTEGER NOT NULL, challenge TEXT,
    game_speed REAL NOT NULL, engine_version TEXT NOT NULL, version INTEGER NOT NULL, phase TEXT NOT NULL,
    ante INTEGER NOT NULL, round INTEGER NOT NULL, dollars REAL NOT NULL, won INTEGER NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL{owner}
);
CREATE TABLE commands (run_id TEXT NOT NULL, seq INTEGER NOT NULL, command TEXT NOT NULL, PRIMARY KEY (run_id, seq));
"""
AT = "2026-01-01T00:00:00+00:00"


def old_database(path, owners: bool) -> None:
    db = sqlite3.connect(path)
    db.executescript(OLD_SCHEMA.format(owner=",\n    owner TEXT NOT NULL" if owners else ""))
    runs = {"played": [{"cmd": "select_blind"}, {"cmd": "play", "cards": [0, 1, 2, 3, 4]}],
            "cheated": [{"cmd": "cheat", "dollars": 50}]}
    for run_id, commands in runs.items():
        values = [run_id, "TESTSEED", "b_red", 1, None, 1.0, "0.3.0", len(commands), "playing", 1, 1, 4, 0, AT, AT]
        db.execute(f"INSERT INTO runs VALUES ({', '.join('?' * (len(values) + owners))})",
                   values + (["p1"] if owners else []))
        db.executemany("INSERT INTO commands VALUES (?, ?, ?)",
                       [(run_id, i, json.dumps(c)) for i, c in enumerate(commands)])
    db.commit()
    db.close()


def test_import_sqlite(pg, tmp_path):
    path = tmp_path / "balatro.db"
    old_database(path, owners=True)
    repo, engine = pg(), BalatroEngine()
    assert import_sqlite(repo, engine, str(path)) == 2
    assert import_sqlite(repo, engine, str(path)) == 0  # already there
    played, cheated = repo.get("played"), repo.get("cheated")
    assert played.owner == "p1" and played.version == 2 and not played.settings.seeded
    assert played.stats.best_hand == 56 and played.stats.career["c_hands_played"] == 1
    assert not played.debug and cheated.debug and not cheated.counts
    assert len(repo.list("p1", 10, 0)) == 2

    repo.set_stats("played", RunStats(), False)
    assert rebuild_stats(repo, engine) == 2
    assert repo.get("played").stats == played.stats


def test_import_runs_from_before_owners(pg, tmp_path):
    path = tmp_path / "older.db"
    old_database(path, owners=False)
    repo = pg()
    import_sqlite(repo, BalatroEngine(), str(path))
    assert {r.id for r in repo.runs_of(ANONYMOUS_PLAYER)} == {"played", "cheated"}
