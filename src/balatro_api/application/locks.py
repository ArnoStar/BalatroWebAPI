"""One lock per run: a run's actions are applied one after the other."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager


class RunLocks:
    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        self._users: dict[str, int] = {}

    @contextmanager
    def hold(self, run_id: str) -> Iterator[None]:
        with self._guard:
            lock = self._locks.setdefault(run_id, threading.Lock())
            self._users[run_id] = self._users.get(run_id, 0) + 1
        try:
            with lock:
                yield
        finally:
            with self._guard:
                self._users[run_id] -= 1
                if not self._users[run_id]:
                    del self._users[run_id]
                    del self._locks[run_id]
