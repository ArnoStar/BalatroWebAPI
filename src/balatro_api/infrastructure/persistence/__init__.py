"""Where runs are stored."""

from .memory import InMemoryGameRepository
from .sqlite import SqliteGameRepository

__all__ = ["InMemoryGameRepository", "SqliteGameRepository"]
