"""Runs stored in SQLite: one row per run, one row per command (append-only).

The commands are the whole game (see domain.run), so this is all there is
to store; the progress columns only serve the run list.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from balatro_api.domain import (
    ANONYMOUS_PLAYER,
    Command,
    GameNotFound,
    GameSettings,
    Phase,
    Progress,
    Run,
    RunSummary,
    VersionConflict,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    seed TEXT NOT NULL,
    deck TEXT NOT NULL,
    stake INTEGER NOT NULL,
    challenge TEXT,
    game_speed REAL NOT NULL,
    engine_version TEXT NOT NULL,
    version INTEGER NOT NULL,
    phase TEXT NOT NULL,
    ante INTEGER NOT NULL,
    round INTEGER NOT NULL,
    dollars REAL NOT NULL,
    won INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    owner TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS runs_updated ON runs (updated_at DESC);
CREATE TABLE IF NOT EXISTS commands (
    run_id TEXT NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    command TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);
"""

RUN_COLUMNS = ("id, seed, deck, stake, challenge, game_speed, engine_version, version, phase, ante, round, dollars, "
               "won, created_at, updated_at, owner")

# databases made before runs had owners: their runs are the anonymous player's
MIGRATIONS = f"""
ALTER TABLE runs ADD COLUMN owner TEXT NOT NULL DEFAULT '{ANONYMOUS_PLAYER}';
"""
INDEXES = "CREATE INDEX IF NOT EXISTS runs_owner_updated ON runs (owner, updated_at DESC);"


class SqliteGameRepository:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.execute("PRAGMA foreign_keys = ON")
            if self.path != ":memory:":
                self._db.execute("PRAGMA journal_mode = WAL")
            self._db.executescript(SCHEMA)
            columns = {r["name"] for r in self._db.execute("PRAGMA table_info(runs)")}
            if "owner" not in columns:
                self._db.executescript(MIGRATIONS)
            self._db.executescript(INDEXES)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # ------------------------------------------------------------ rows
    @staticmethod
    def _summary(row: sqlite3.Row) -> RunSummary:
        settings = GameSettings(seed=row["seed"], deck=row["deck"], stake=row["stake"], challenge=row["challenge"],
                                game_speed=row["game_speed"])
        progress = Progress(phase=Phase(row["phase"]), ante=row["ante"], round=row["round"], dollars=row["dollars"],
                            won=bool(row["won"]))
        return RunSummary(id=row["id"], settings=settings, progress=progress, version=row["version"],
                          created_at=datetime.fromisoformat(row["created_at"]),
                          updated_at=datetime.fromisoformat(row["updated_at"]), owner=row["owner"])

    @staticmethod
    def _progress(run: Run) -> tuple[str, int, int, float, int]:
        p = run.progress
        return p.phase.value, p.ante, p.round, p.dollars, int(p.won)

    def _insert_commands(self, run: Run, start: int) -> None:
        self._db.executemany("INSERT INTO commands (run_id, seq, command) VALUES (?, ?, ?)",
                             [(run.id, i, json.dumps(c.as_dict(), separators=(",", ":")))
                              for i, c in enumerate(run.commands[start:], start)])

    # ------------------------------------------------------------ port
    def add(self, run: Run) -> None:
        s = run.settings
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                self._db.execute(
                    f"INSERT INTO runs ({RUN_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (run.id, s.seed, s.deck, s.stake, s.challenge, s.game_speed, run.engine_version, run.version,
                     *self._progress(run), run.created_at.isoformat(), run.updated_at.isoformat(), run.owner))
                self._insert_commands(run, 0)
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def get(self, run_id: str) -> Run:
        with self._lock:
            row = self._db.execute(f"SELECT {RUN_COLUMNS} FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                raise GameNotFound(run_id)
            commands = [Command(json.loads(r["command"])) for r in self._db.execute(
                "SELECT command FROM commands WHERE run_id = ? ORDER BY seq", (run_id,))]
        s = self._summary(row)
        return Run(id=s.id, settings=s.settings, engine_version=row["engine_version"], progress=s.progress,
                   created_at=s.created_at, updated_at=s.updated_at, commands=commands, owner=s.owner)

    def save(self, run: Run, expected_version: int) -> None:
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                cur = self._db.execute(
                    "UPDATE runs SET version = ?, phase = ?, ante = ?, round = ?, dollars = ?, won = ?, updated_at = ? "
                    "WHERE id = ? AND version = ?",
                    (run.version, *self._progress(run), run.updated_at.isoformat(), run.id, expected_version))
                if cur.rowcount != 1:
                    row = self._db.execute("SELECT version FROM runs WHERE id = ?", (run.id,)).fetchone()
                    if row is None:
                        raise GameNotFound(run.id)
                    raise VersionConflict(expected_version, row["version"])
                self._insert_commands(run, expected_version)
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def delete(self, run_id: str) -> None:
        with self._lock:
            cur = self._db.execute("DELETE FROM runs WHERE id = ?", (run_id,))
            if cur.rowcount != 1:
                raise GameNotFound(run_id)

    def list(self, owner: str, limit: int, offset: int) -> list[RunSummary]:
        with self._lock:
            rows = self._db.execute(
                f"SELECT {RUN_COLUMNS} FROM runs WHERE owner = ? ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (owner, limit, offset)).fetchall()
        return [self._summary(r) for r in rows]
