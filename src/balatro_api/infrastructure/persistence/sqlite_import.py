"""Reads the runs of the SQLite database the API used before PostgreSQL
(``python -m balatro_api.manage import-sqlite <file>`` copies them over).

Those runs don't know whether the player chose the seed (they count as
unseeded) nor their stats (the import replays them).  A run that used a
debug command is marked as such, from its commands.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from balatro_api.domain import ANONYMOUS_PLAYER, Command, GameSettings, Phase, Progress, Run

DEBUG_COMMANDS = ("cheat", "add_joker", "add_tag", "add_voucher")


def read_runs(path: str | Path) -> Iterator[Run]:
    if not Path(path).exists():
        raise FileNotFoundError(path)
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        columns = {r["name"] for r in db.execute("PRAGMA table_info(runs)")}
        owner = "owner" if "owner" in columns else f"'{ANONYMOUS_PLAYER}' AS owner"
        rows = db.execute(f"SELECT id, seed, deck, stake, challenge, game_speed, engine_version, phase, ante, round, "
                          f"dollars, won, created_at, updated_at, {owner} FROM runs ORDER BY created_at").fetchall()
        for row in rows:
            commands = [Command(json.loads(r["command"])) for r in db.execute(
                "SELECT command FROM commands WHERE run_id = ? ORDER BY seq", (row["id"],))]
            yield Run(
                id=row["id"],
                settings=GameSettings(seed=row["seed"], deck=row["deck"], stake=row["stake"],
                                      challenge=row["challenge"], game_speed=row["game_speed"]),
                engine_version=row["engine_version"],
                progress=Progress(phase=Phase(row["phase"]), ante=row["ante"], round=row["round"],
                                  dollars=row["dollars"], won=bool(row["won"])),
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
                commands=commands, owner=row["owner"],
                debug=any(c.payload.get("cmd") in DEBUG_COMMANDS for c in commands))
    finally:
        db.close()
