from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from balatro_api.bootstrap import build_use_cases
from balatro_api.config import Settings
from balatro_api.infrastructure.persistence import PostgresGameRepository
from balatro_api.presentation.http import create_app

# a PostgreSQL database the tests may use (each test gets its own schema, dropped
# after it); without it the PostgreSQL tests are skipped. `make test` sets it to
# the database of `make db`.
PG_URL = os.environ.get("BALATRO_API_TEST_DATABASE_URL")


@pytest.fixture
def client() -> TestClient:
    settings = Settings(database="memory", debug_commands=True)
    return TestClient(create_app(build_use_cases(settings)))


@pytest.fixture
def pg() -> Iterator[Callable[[], PostgresGameRepository]]:
    """Makes repositories on one fresh schema (several = several servers)."""
    if not PG_URL:
        pytest.skip("BALATRO_API_TEST_DATABASE_URL is not set")
    schema = f"test_{uuid.uuid4().hex[:12]}"
    made: list[PostgresGameRepository] = []

    def make() -> PostgresGameRepository:
        made.append(PostgresGameRepository(PG_URL, schema=schema))  # type: ignore[arg-type]
        return made[-1]

    yield make
    for r in made:
        r.close()
    with psycopg.connect(PG_URL, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
