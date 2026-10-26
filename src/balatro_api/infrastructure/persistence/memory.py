"""Runs kept in memory (lost when the server stops).  For tests and demos."""

from __future__ import annotations

import builtins
import copy
import threading

from balatro_api.application import statistics
from balatro_api.application.dto import GlobalStats, LeaderboardName
from balatro_api.application.ports import BoardPage
from balatro_api.domain import GameNotFound, Run, RunSummary, VersionConflict


class InMemoryGameRepository:
    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}
        self._names: dict[str, str | None] = {}
        self._lock = threading.Lock()

    def _remember(self, run: Run) -> None:
        if run.owner_name is not None:
            self._names[run.owner] = run.owner_name

    def add(self, run: Run) -> None:
        with self._lock:
            self._runs[run.id] = copy.deepcopy(run)
            self._remember(run)

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
            self._remember(run)

    def delete(self, run_id: str) -> None:
        with self._lock:
            if self._runs.pop(run_id, None) is None:
                raise GameNotFound(run_id)

    def list(self, owner: str, limit: int, offset: int) -> list[RunSummary]:
        with self._lock:
            runs = sorted((r for r in self._runs.values() if r.owned_by(owner) and not r.replay),
                          key=lambda r: r.updated_at, reverse=True)
            return [r.summary() for r in runs[offset:offset + limit]]

    def runs_of(self, owner: str) -> builtins.list[RunSummary]:
        with self._lock:
            return sorted((r.summary() for r in self._runs.values() if r.owned_by(owner)), key=lambda r: r.updated_at)

    def _all(self) -> builtins.list[RunSummary]:
        with self._lock:
            return [r.summary() for r in self._runs.values()]

    def leaderboard(self, board: LeaderboardName, deck: str | None, stake: int | None, limit: int,
                    owner: str) -> BoardPage:
        runs = self._all()
        with self._lock:
            names = dict(self._names)
        return statistics.leaderboard(runs, names, board, deck, stake, limit, owner)

    def global_stats(self) -> GlobalStats:
        return statistics.global_stats(self._all())
