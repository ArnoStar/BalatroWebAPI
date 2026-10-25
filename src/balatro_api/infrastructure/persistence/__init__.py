"""Where runs are kept: PostgreSQL, or memory (tests and demos)."""

from .memory import InMemoryGameRepository
from .postgres import PostgresGameRepository

__all__ = ["InMemoryGameRepository", "PostgresGameRepository"]
