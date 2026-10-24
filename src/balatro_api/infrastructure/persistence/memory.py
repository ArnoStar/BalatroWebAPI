"""Runs kept in memory (lost when the server stops).  For tests and demos."""

from __future__ import annotations

import copy
import threading

from balatro_api.domain import GameNotFound, Run, RunSummary, VersionConflict


class InMemoryGameRepository:
    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}
        self._lock = threading.Lock()

    def add(self, run: Run) -> None:
        with self._lock:
            self._runs[run.id] = copy.deepcopy(run)

    def get(self, run_id: str) -> Run:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise GameNotFound(run_id)
            return copy.deepcopy(run)

    def save(self, run: Run, expected_version: int) -> None:
        with self._lock:
            stored = self._runs.get(run.id)
            if stored is None:
                raise GameNotFound(run.id)
            if stored.version != expected_version:
                raise VersionConflict(expected_version, stored.version)
            self._runs[run.id] = copy.deepcopy(run)

    def delete(self, run_id: str) -> None:
        with self._lock:
            if self._runs.pop(run_id, None) is None:
                raise GameNotFound(run_id)

    def list(self, owner: str, limit: int, offset: int) -> list[RunSummary]:
        with self._lock:
            runs = sorted((r for r in self._runs.values() if r.owned_by(owner)), key=lambda r: r.updated_at,
                          reverse=True)
            return [r.summary() for r in runs[offset:offset + limit]]
