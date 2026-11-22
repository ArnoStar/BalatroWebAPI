"""Runs and matches kept in memory (lost when the server stops).  For tests and demos."""

from __future__ import annotations

import builtins
import copy
import threading
from datetime import datetime
from typing import Any

from balatro_api.application import statistics
from balatro_api.application.dto import GlobalStats, LeaderboardName
from balatro_api.application.ports import BoardPage, PlayerRecord
from balatro_api.domain import (
    GameNotFound,
    Match,
    MatchNotFound,
    MatchStatus,
    ModRecord,
    ModVersion,
    Run,
    RunSummary,
    VersionConflict,
    logic,
)


class InMemoryGameRepository:
    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}
        self._names: dict[str, str | None] = {}
        self._players: dict[str, PlayerRecord] = {}
        self._pointers: dict[str, dict[int, dict[str, Any]]] = {}
        self._matches: dict[str, Match] = {}
        self._packages: dict[str, dict[str, Any]] = {}
        self._mods: dict[str, ModRecord] = {}
        self._versions: dict[str, builtins.list[ModVersion]] = {}
        self._installs: dict[str, set[str]] = {}
        self._lock = threading.Lock()

    def _remember(self, run: Run) -> None:
        if run.owner_name is not None:
            self._names[run.owner] = run.owner_name

    def player(self, player_id: str) -> PlayerRecord | None:
        with self._lock:
            p = self._players.get(player_id)
            name = self._names.get(player_id)
            if p is None:
                return PlayerRecord(id=player_id, name=name) if player_id in self._names else None
            return PlayerRecord(id=player_id, name=name or p.name, private=p.private, all_unlocked=p.all_unlocked)

    def set_player(self, player_id: str, name: str | None, *, private: bool | None = None,
                   all_unlocked: bool | None = None) -> PlayerRecord:
        with self._lock:
            p = self._players.get(player_id) or PlayerRecord(id=player_id)
            if name is not None:
                self._names[player_id] = name
            p = PlayerRecord(id=player_id, name=self._names.get(player_id),
                             private=p.private if private is None else private,
                             all_unlocked=p.all_unlocked if all_unlocked is None else all_unlocked)
            self._players[player_id] = p
            return p

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
            self._pointers.pop(run_id, None)

    def save_pointer(self, run_id: str, version: int, pointer: dict[str, Any]) -> None:
        with self._lock:
            if run_id in self._runs:
                self._pointers.setdefault(run_id, {})[version] = copy.deepcopy(pointer)

    def pointers(self, run_id: str) -> dict[int, dict[str, Any]]:
        with self._lock:
            return copy.deepcopy(self._pointers.get(run_id, {}))

    def list(self, owner: str, limit: int, offset: int) -> list[RunSummary]:
        with self._lock:
            runs = sorted((r for r in self._runs.values()
                           if r.owned_by(owner) and not r.replay and r.settings.mode is None),
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

    # ------------------------------------------------------------ matches
    def add_match(self, match: Match) -> None:
        with self._lock:
            self._matches[match.id] = copy.deepcopy(match)

    def get_match(self, match_id: str) -> Match:
        with self._lock:
            match = self._matches.get(match_id)
            if match is None:
                raise MatchNotFound(match_id)
            return copy.deepcopy(match)

    def match_by_code(self, code: str) -> Match:
        with self._lock:
            for m in self._matches.values():
                if m.code == code and m.status is MatchStatus.LOBBY:
                    return copy.deepcopy(m)
        raise MatchNotFound(code)

    def current_match(self, player_id: str) -> Match | None:
        with self._lock:
            mine = [m for m in self._matches.values() if m.active and m.seat_of(player_id) is not None]
            return copy.deepcopy(max(mine, key=lambda m: m.updated_at)) if mine else None

    def save_match(self, match: Match, expected_version: int) -> None:
        with self._lock:
            stored = self._matches.get(match.id)
            if stored is None:
                raise MatchNotFound(match.id)
            if stored.version != expected_version:
                raise VersionConflict(expected_version, stored.version)
            saved = copy.deepcopy(match)
            saved.version = expected_version + 1
            self._matches[match.id] = saved

    def finished_matches(self, player_id: str, limit: int | None = None,
                         before: datetime | None = None) -> builtins.list[Match]:
        with self._lock:
            mine = [m for m in self._matches.values()
                    if m.played and m.seat_of(player_id) is not None and (before is None or m.updated_at < before)]
            mine.sort(key=lambda m: m.updated_at, reverse=True)
            return [copy.deepcopy(m) for m in mine[:limit]]

    # ------------------------------------------------------------ mods
    def put_package(self, hash: str, package: dict[str, Any], at: datetime) -> None:
        with self._lock:
            self._packages.setdefault(hash, copy.deepcopy(package))

    def package(self, hash: str) -> dict[str, Any] | None:
        with self._lock:
            p = self._packages.get(hash)
            return copy.deepcopy(p) if p is not None else None

    def logic(self, hashes: builtins.list[str] | tuple[str, ...]) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {h: copy.deepcopy(logic(self._packages[h])) for h in hashes if h in self._packages}

    def get_mod(self, mod_id: str) -> ModRecord | None:
        with self._lock:
            r = self._mods.get(mod_id)
            return copy.deepcopy(r) if r is not None else None

    def save_mod(self, record: ModRecord) -> None:
        with self._lock:
            self._mods[record.id] = copy.deepcopy(record)

    def add_version(self, version: ModVersion) -> None:
        with self._lock:
            versions = self._versions.setdefault(version.mod_id, [])
            if not any(v.version == version.version for v in versions):
                versions.append(version)

    def versions(self, mod_id: str) -> builtins.list[ModVersion]:
        with self._lock:
            return sorted(self._versions.get(mod_id, []), key=lambda v: v.created_at, reverse=True)

    def find_mods(self, query: str | None, tag: str | None, sort: str, limit: int, offset: int,
                  owner: str | None = None) -> tuple[builtins.list[ModRecord], int]:
        with self._lock:
            found = [r for r in self._mods.values() if (r.owner == owner if owner is not None else r.listed)]
        if query:
            q = query.lower()
            found = [r for r in found if q in r.id.lower() or q in r.name.lower() or q in r.description.lower()]
        if tag:
            found = [r for r in found if tag in r.tags]
        keys = {"popular": lambda r: (-r.installs, -r.updated_at.timestamp(), r.id),
                "new": lambda r: (-r.created_at.timestamp(), r.id),
                "updated": lambda r: (-r.updated_at.timestamp(), r.id),
                "name": lambda r: (r.name.lower(), r.id)}
        found.sort(key=keys.get(sort, keys["popular"]))
        return [copy.deepcopy(r) for r in found[offset:offset + limit]], len(found)

    def add_install(self, mod_id: str, player_id: str, at: datetime) -> int:
        with self._lock:
            players = self._installs.setdefault(mod_id, set())
            players.add(player_id)
            if mod_id in self._mods:
                self._mods[mod_id].installs = len(players)
            return len(players)
