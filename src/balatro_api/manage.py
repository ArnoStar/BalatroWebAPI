"""Maintenance commands: ``python -m balatro_api.manage <command>``.

  import-sqlite FILE   copy the runs of the SQLite database the API used
                       before PostgreSQL (replaying each for its stats)
  rebuild-stats        replay every run and store its stats again (after an
                       engine release that counts them differently)

The database is BALATRO_API_DATABASE_URL's, as for the server.
"""

from __future__ import annotations

import argparse
import logging
import sys

from .config import Settings
from .infrastructure.engine import BalatroEngine
from .infrastructure.persistence import PostgresGameRepository
from .infrastructure.persistence.sqlite_import import read_runs

log = logging.getLogger("balatro_api.manage")


def import_sqlite(repo: PostgresGameRepository, engine: BalatroEngine, path: str) -> int:
    known = set(repo.ids())
    done = 0
    for run in read_runs(path):
        if run.id in known:
            continue
        try:
            run.stats = engine.run_stats(run)
        except Exception as e:  # a run that no longer replays keeps empty stats
            log.warning("run %s: no stats (%s)", run.id, e)
        finally:
            engine.forget(run.id)
        repo.add(run)
        done += 1
    log.info("imported %d runs (%d were already there)", done, len(known))
    return done


def rebuild_stats(repo: PostgresGameRepository, engine: BalatroEngine) -> int:
    done = 0
    for run_id in repo.ids():
        run = repo.get(run_id)
        try:
            repo.set_stats(run_id, engine.run_stats(run), run.debug)
            done += 1
        except Exception as e:
            log.warning("run %s: %s", run_id, e)
        finally:
            engine.forget(run_id)
    log.info("rebuilt the stats of %d runs", done)
    return done


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m balatro_api.manage", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("import-sqlite").add_argument("file")
    sub.add_parser("rebuild-stats")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = Settings.from_env()
    if settings.database == "memory":
        parser.error("BALATRO_API_DATABASE_URL must be a PostgreSQL database")
    repo = PostgresGameRepository(settings.database)
    engine = BalatroEngine(cache_size=1)
    try:
        if args.command == "import-sqlite":
            import_sqlite(repo, engine, args.file)
        else:
            rebuild_stats(repo, engine)
    finally:
        repo.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
