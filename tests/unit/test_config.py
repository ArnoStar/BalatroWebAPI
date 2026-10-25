"""Settings from the environment."""

from __future__ import annotations

import pytest

from balatro_api.config import DEFAULT_DATABASE, Settings


def test_the_database():
    assert Settings.from_env({}).database == DEFAULT_DATABASE
    url = "postgresql://balatro:pw@api-db:5432/balatro"
    assert Settings.from_env({"BALATRO_API_DATABASE_URL": url}).database == url
    assert Settings.from_env({"BALATRO_API_DATABASE_URL": "memory"}).database == "memory"
    assert Settings.from_env({"BALATRO_API_DATABASE": "memory"}).database == "memory"


def test_the_old_sqlite_setting_is_refused_plainly():
    """A compose file from before PostgreSQL: the server says what to do."""
    with pytest.raises(ValueError, match="BALATRO_API_DATABASE_URL.*import-sqlite"):
        Settings.from_env({"BALATRO_API_DATABASE": "/data/balatro.db"})
    url = "postgresql://balatro:pw@api-db:5432/balatro"
    both = {"BALATRO_API_DATABASE": "/data/balatro.db", "BALATRO_API_DATABASE_URL": url}
    assert Settings.from_env(both).database == url
