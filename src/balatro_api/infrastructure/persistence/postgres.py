"""Runs stored in PostgreSQL: one row per run, one row per command (append-only).

The commands are the whole game (see domain.run), so they are all there is to
store; the other columns of ``runs`` are caches for listing runs and for
statistics (``Progress``, ``RunStats``), which a replay can always rebuild.
The high scores have their own columns (leaderboards sort by them); the rest
of the run's stats is a JSON document.

The schema is made by the numbered ``MIGRATIONS`` when the repository starts
(each applied once, in order, under a lock, so several servers can start
together).  Never change a migration that has been released: add one.
"""

from __future__ import annotations

import builtins
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from psycopg import Connection, sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import DictRow, dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool, PoolTimeout

from balatro_api.application.dto import (
    DeckPopularity,
    GlobalStats,
    JokerPopularity,
    LeaderboardName,
    StakePopularity,
    UsageCount,
)
from balatro_api.application.ports import BoardPage, BoardRow
from balatro_api.application.statistics import POKER_HANDS, number, score
from balatro_api.domain import (
    Command,
    GameNotFound,
    GameSettings,
    Phase,
    Progress,
    Run,
    RunStats,
    RunSummary,
    VersionConflict,
)

MIGRATIONS: tuple[str, ...] = (
    # 1: runs, their commands, and the players' display names
    """
    CREATE TABLE players (
        id TEXT PRIMARY KEY,
        name TEXT,
        updated_at TIMESTAMPTZ NOT NULL
    );
    CREATE TABLE runs (
        id TEXT PRIMARY KEY,
        owner TEXT NOT NULL,
        seed TEXT NOT NULL,
        seeded BOOLEAN NOT NULL,
        deck TEXT NOT NULL,
        stake SMALLINT NOT NULL,
        challenge TEXT,
        game_speed DOUBLE PRECISION NOT NULL,
        engine_version TEXT NOT NULL,
        version INTEGER NOT NULL,
        phase TEXT NOT NULL,
        ante INTEGER NOT NULL,
        round INTEGER NOT NULL,
        dollars DOUBLE PRECISION NOT NULL,
        won BOOLEAN NOT NULL,
        debug BOOLEAN NOT NULL,
        best_hand DOUBLE PRECISION NOT NULL,
        furthest_ante INTEGER NOT NULL,
        furthest_round INTEGER NOT NULL,
        most_money DOUBLE PRECISION NOT NULL,
        boss_streak INTEGER NOT NULL,
        stats JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL,
        counted BOOLEAN GENERATED ALWAYS AS (NOT seeded AND challenge IS NULL AND NOT debug) STORED
    );
    CREATE INDEX runs_owner_updated ON runs (owner, updated_at DESC);
    CREATE INDEX runs_counted_owner ON runs (owner) WHERE counted;
    CREATE TABLE commands (
        run_id TEXT NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
        seq INTEGER NOT NULL,
        command JSONB NOT NULL,
        PRIMARY KEY (run_id, seq)
    );
    """,
)

RUN_COLUMNS = ("id", "owner", "seed", "seeded", "deck", "stake", "challenge", "game_speed", "engine_version", "version",
               "phase", "ante", "round", "dollars", "won", "debug", "best_hand", "furthest_ante", "furthest_round",
               "most_money", "boss_streak", "stats", "created_at", "updated_at")
SELECT_RUNS = sql.SQL("SELECT {} FROM runs").format(sql.SQL(", ").join(sql.Identifier(c) for c in RUN_COLUMNS))
BOARD_COLUMNS = {"best_hand": "best_hand", "highest_ante": "furthest_ante", "highest_round": "furthest_round",
                 "most_money": "most_money", "boss_streak": "boss_streak"}


class DatabaseUnavailable(RuntimeError):
    """The database doesn't answer when the server starts."""


def where(url: str) -> str:
    """The database's address, without the password."""
    try:
        d = conninfo_to_dict(url)
    except Exception:
        return "(an unreadable URL)"
    return f"{d.get('host', 'localhost')}:{d.get('port', 5432)}/{d.get('dbname', '')}"


class PostgresGameRepository:
    """``url``: a libpq connection string (postgresql://user:password@host/db).
    ``schema``: keep the tables in this schema (made if needed) instead of the
    default one.  ``connect_timeout``: how long to wait for the database at
    start (seconds) before raising DatabaseUnavailable."""

    def __init__(self, url: str, schema: str | None = None, max_connections: int = 10,
                 connect_timeout: float = 30) -> None:
        self.schema = schema

        def configure(conn: Connection[Any]) -> None:
            conn.execute("SET TIME ZONE 'UTC'")
            if schema:
                conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            conn.commit()

        if schema:
            with Connection.connect(url, autocommit=True) as conn:
                conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))
        self._pool: ConnectionPool[Connection[DictRow]] = ConnectionPool(
            url, min_size=1, max_size=max_connections, configure=configure, open=False,
            kwargs={"row_factory": dict_row}, connection_class=Connection[DictRow])
        try:
            self._pool.open(wait=True, timeout=connect_timeout)
        except PoolTimeout:
            self._pool.close()
            raise DatabaseUnavailable(
                f"PostgreSQL at {where(url)} doesn't answer (BALATRO_API_DATABASE_URL). In Docker, the api-db "
                "service of BalatroFrontEnd's docker-compose.yml is the API's database") from None
        self.migrate()

    def close(self) -> None:
        self._pool.close()

    @contextmanager
    def _tx(self) -> Iterator[Connection[DictRow]]:
        with self._pool.connection() as conn, conn.transaction():
            yield conn

    def migrate(self) -> None:
        with self._tx() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtext('balatro_api.migrations'))")
            conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, "
                         "applied_at TIMESTAMPTZ NOT NULL DEFAULT now())")
            row = conn.execute("SELECT COALESCE(MAX(version), 0) AS v FROM schema_migrations").fetchone()
            done = row["v"] if row else 0
            for version, script in enumerate(MIGRATIONS, 1):
                if version > done:
                    conn.execute(script.encode())
                    conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))

    # ------------------------------------------------------------ rows
    @staticmethod
    def _summary(row: DictRow) -> RunSummary:
        settings = GameSettings(seed=row["seed"], deck=row["deck"], stake=row["stake"], challenge=row["challenge"],
                                game_speed=row["game_speed"], seeded=row["seeded"])
        progress = Progress(phase=Phase(row["phase"]), ante=row["ante"], round=row["round"], dollars=row["dollars"],
                            won=row["won"])
        stats = RunStats.from_json(row["stats"], best_hand=row["best_hand"], furthest_ante=row["furthest_ante"],
                                   furthest_round=row["furthest_round"], most_money=row["most_money"],
                                   boss_streak=row["boss_streak"])
        return RunSummary(id=row["id"], settings=settings, progress=progress, version=row["version"],
                          created_at=row["created_at"], updated_at=row["updated_at"], owner=row["owner"],
                          stats=stats, debug=row["debug"])

    @staticmethod
    def _cached(run: Run) -> dict[str, Any]:
        """The columns derived from the run's commands."""
        p, s = run.progress, run.stats
        return {"version": run.version, "phase": p.phase.value, "ante": p.ante, "round": p.round,
                "dollars": p.dollars, "won": p.won, "debug": run.debug, "best_hand": s.best_hand,
                "furthest_ante": s.furthest_ante, "furthest_round": s.furthest_round, "most_money": s.most_money,
                "boss_streak": s.boss_streak, "stats": Jsonb(s.to_json()), "updated_at": run.updated_at}

    @staticmethod
    def _insert_commands(conn: Connection[DictRow], run: Run, start: int) -> None:
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO commands (run_id, seq, command) VALUES (%s, %s, %s)",
                            [(run.id, i, Jsonb(c.as_dict())) for i, c in enumerate(run.commands[start:], start)])

    @staticmethod
    def _remember(conn: Connection[DictRow], run: Run) -> None:
        if run.owner_name is not None:
            conn.execute("INSERT INTO players (id, name, updated_at) VALUES (%s, %s, %s) ON CONFLICT (id) DO UPDATE "
                         "SET name = EXCLUDED.name, updated_at = EXCLUDED.updated_at "
                         "WHERE players.updated_at <= EXCLUDED.updated_at",
                         (run.owner, run.owner_name, run.updated_at))

    # ------------------------------------------------------------ port
    def add(self, run: Run) -> None:
        s = run.settings
        values = {"id": run.id, "owner": run.owner, "seed": s.seed, "seeded": s.seeded, "deck": s.deck,
                  "stake": s.stake, "challenge": s.challenge, "game_speed": s.game_speed,
                  "engine_version": run.engine_version, "created_at": run.created_at, **self._cached(run)}
        query = sql.SQL("INSERT INTO runs ({}) VALUES ({})").format(
            sql.SQL(", ").join(sql.Identifier(c) for c in values),
            sql.SQL(", ").join(sql.Placeholder(c) for c in values))
        with self._tx() as conn:
            conn.execute(query, values)
            self._insert_commands(conn, run, 0)
            self._remember(conn, run)

    def get(self, run_id: str) -> Run:
        with self._tx() as conn:
            row = conn.execute(sql.SQL("{} WHERE id = %s").format(SELECT_RUNS), (run_id,)).fetchone()
            if row is None:
                raise GameNotFound(run_id)
            commands = [Command(r["command"]) for r in conn.execute(
                "SELECT command FROM commands WHERE run_id = %s ORDER BY seq", (run_id,))]
            name = conn.execute("SELECT name FROM players WHERE id = %s", (row["owner"],)).fetchone()
        s = self._summary(row)
        return Run(id=s.id, settings=s.settings, engine_version=row["engine_version"], progress=s.progress,
                   created_at=s.created_at, updated_at=s.updated_at, commands=commands, owner=s.owner,
                   owner_name=name["name"] if name else None, stats=s.stats, debug=s.debug)

    def save(self, run: Run, expected_version: int) -> None:
        values = self._cached(run)
        query = sql.SQL("UPDATE runs SET {} WHERE id = %(id)s AND version = %(expected)s").format(
            sql.SQL(", ").join(sql.SQL("{} = {}").format(sql.Identifier(c), sql.Placeholder(c)) for c in values))
        with self._tx() as conn:
            cur = conn.execute(query, {**values, "id": run.id, "expected": expected_version})
            if cur.rowcount != 1:
                row = conn.execute("SELECT version FROM runs WHERE id = %s", (run.id,)).fetchone()
                if row is None:
                    raise GameNotFound(run.id)
                raise VersionConflict(expected_version, row["version"])
            self._insert_commands(conn, run, expected_version)
            self._remember(conn, run)

    def set_stats(self, run_id: str, stats: RunStats, debug: bool) -> None:
        """Replace a run's cached stats (after a replay with a newer engine)."""
        s = stats
        with self._tx() as conn:
            conn.execute("UPDATE runs SET best_hand = %s, furthest_ante = %s, furthest_round = %s, most_money = %s, "
                         "boss_streak = %s, stats = %s, debug = %s WHERE id = %s",
                         (s.best_hand, s.furthest_ante, s.furthest_round, s.most_money, s.boss_streak,
                          Jsonb(s.to_json()), debug, run_id))

    def ids(self) -> builtins.list[str]:
        with self._tx() as conn:
            return [r["id"] for r in conn.execute("SELECT id FROM runs ORDER BY created_at")]

    def delete(self, run_id: str) -> None:
        with self._tx() as conn:
            if conn.execute("DELETE FROM runs WHERE id = %s", (run_id,)).rowcount != 1:
                raise GameNotFound(run_id)

    def list(self, owner: str, limit: int, offset: int) -> list[RunSummary]:
        with self._tx() as conn:
            rows = conn.execute(sql.SQL("{} WHERE owner = %s ORDER BY updated_at DESC LIMIT %s OFFSET %s").format(
                SELECT_RUNS), (owner, limit, offset)).fetchall()
        return [self._summary(r) for r in rows]

    def runs_of(self, owner: str) -> builtins.list[RunSummary]:
        with self._tx() as conn:
            rows = conn.execute(sql.SQL("{} WHERE owner = %s ORDER BY updated_at").format(SELECT_RUNS),
                                (owner,)).fetchall()
        return [self._summary(r) for r in rows]

    # ------------------------------------------------------------ everyone
    def leaderboard(self, board: LeaderboardName, deck: str | None, stake: int | None, limit: int,
                    owner: str) -> BoardPage:
        best: sql.Composable
        if board == "wins":
            best = sql.SQL("""
                SELECT owner, COUNT(*)::float8 AS value, NULL::text AS deck, NULL::smallint AS stake,
                       NULL::boolean AS won, MAX(updated_at) AS at
                FROM counted WHERE won GROUP BY owner""")
        else:
            col = sql.Identifier(BOARD_COLUMNS[board])
            best = sql.SQL("""
                SELECT DISTINCT ON (owner) owner, {col}::float8 AS value, deck, stake, won, updated_at AS at
                FROM counted WHERE {col} > 0
                ORDER BY owner, {col} DESC, updated_at""").format(col=col)
        query = sql.SQL("""
            WITH counted AS (
                SELECT * FROM runs
                WHERE counted AND (%(deck)s::text IS NULL OR deck = %(deck)s)
                  AND (%(stake)s::int IS NULL OR stake = %(stake)s)
            ), best AS ({best}), ranked AS (
                SELECT best.*, RANK() OVER (ORDER BY value DESC) AS rank,
                       ROW_NUMBER() OVER (ORDER BY value DESC, at) AS pos, COUNT(*) OVER () AS players
                FROM best
            )
            SELECT ranked.*, players.name FROM ranked LEFT JOIN players ON players.id = ranked.owner
            WHERE pos <= %(limit)s OR owner = %(owner)s
            ORDER BY pos""").format(best=best)
        with self._tx() as conn:
            rows = conn.execute(query, {"deck": deck, "stake": stake, "limit": limit, "owner": owner}).fetchall()
        return BoardPage(rows=[BoardRow(rank=r["rank"], owner=r["owner"], name=r["name"], value=r["value"],
                                        deck=r["deck"], stake=r["stake"], won=r["won"], at=r["at"]) for r in rows],
                         players=rows[0]["players"] if rows else 0)

    def global_stats(self) -> GlobalStats:
        career = "COALESCE(SUM((stats->'career'->>%s)::float8), 0)"
        with self._tx() as conn:
            t = conn.execute(f"""
                SELECT COUNT(DISTINCT owner) AS players, COUNT(*) AS runs,
                       COUNT(*) FILTER (WHERE won) AS won,
                       COUNT(*) FILTER (WHERE phase = 'game_over' AND NOT won) AS lost,
                       {career} AS hands_played, {career} AS cards_played, {career} AS dollars_earned,
                       COALESCE(MAX(best_hand), 0) AS best_hand, COALESCE(MAX(furthest_ante), 0) AS highest_ante
                FROM runs WHERE counted""",
                ("c_hands_played", "c_cards_played", "c_dollars_earned")).fetchone()
            decks = conn.execute("SELECT deck, COUNT(*) AS runs, COUNT(*) FILTER (WHERE won) AS wins FROM runs "
                                 "WHERE counted GROUP BY deck ORDER BY runs DESC, deck").fetchall()
            stakes = conn.execute("SELECT stake, COUNT(*) AS runs, COUNT(*) FILTER (WHERE won) AS wins FROM runs "
                                  "WHERE counted GROUP BY stake ORDER BY stake").fetchall()
            jokers = conn.execute("""
                SELECT j.key, COUNT(*) FILTER (WHERE (j.value->>0)::int > 0) AS runs,
                       COUNT(*) FILTER (WHERE won AND (j.value->>1)::int > 0) AS win_runs
                FROM runs, jsonb_each(stats->'jokers') AS j
                WHERE counted GROUP BY j.key
                HAVING COUNT(*) FILTER (WHERE (j.value->>0)::int > 0) > 0
                    OR COUNT(*) FILTER (WHERE won AND (j.value->>1)::int > 0) > 0
                ORDER BY runs DESC, win_runs DESC, j.key LIMIT 20""").fetchall()
            hands = conn.execute("""
                SELECT h.key, SUM(h.value::int) AS count FROM runs, jsonb_each_text(stats->'hands') AS h
                WHERE counted GROUP BY h.key HAVING SUM(h.value::int) > 0""").fetchall()
        assert t is not None
        pos = {k: i for i, k in enumerate(POKER_HANDS)}
        hand_rows: Sequence[DictRow] = sorted(hands, key=lambda r: (-r["count"], pos.get(r["key"], len(pos)),
                                                                     r["key"]))
        return GlobalStats(
            players=t["players"], runs=t["runs"], won=t["won"], lost=t["lost"], hands_played=int(t["hands_played"]),
            cards_played=int(t["cards_played"]), dollars_earned=number(t["dollars_earned"]),
            best_hand=score(t["best_hand"]), highest_ante=t["highest_ante"],
            decks=[DeckPopularity(deck=r["deck"], runs=r["runs"], wins=r["wins"]) for r in decks],
            stakes=[StakePopularity(stake=r["stake"], runs=r["runs"], wins=r["wins"]) for r in stakes],
            jokers=[JokerPopularity(key=r["key"], runs=r["runs"], win_runs=r["win_runs"]) for r in jokers],
            hands=[UsageCount(key=r["key"], count=int(r["count"])) for r in hand_rows])
