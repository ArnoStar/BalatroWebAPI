"""Everyone's multiplayer matches: the leaderboards and the statistics, from the
finished matches and the summaries kept with them (``Matches.summarize``), and,
for coop, the stats of the pair's run (``RunSummary``: its best hand, money,
bosses in a row). Nothing is replayed.

PvP boards are each player's; coop boards are each pair's (both players of a
coop run, whatever their seats): a coop run is theirs together."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from balatro_api.domain import Match, RunSummary

from .dto import (
    CoopGlobalStats,
    MatchDayCount,
    MatchDeckCount,
    MultiplayerBoardName,
    MultiplayerBoardPlayer,
    MultiplayerGlobalStats,
    MultiplayerLeaderboard,
    MultiplayerLeaderboardEntry,
    PvPGlobalStats,
)
from .statistics import score

DAYS = 30
COOP_BOARDS: tuple[MultiplayerBoardName, ...] = (
    "coop_best_hand", "coop_ante", "coop_round", "coop_money", "coop_boss_streak", "coop_wins")


def _num(x: Any) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return v if not math.isnan(v) else 0.0


def _when(m: Match) -> datetime:
    return m.finished_at or m.updated_at


def _seat_summary(m: Match, seat: int) -> dict[str, Any]:
    return next((p for p in (m.summary or {}).get("players") or [] if p.get("seat") == seat), {})


def coop_run_ids(matches: Sequence[Match]) -> list[str]:
    """The runs of the coop matches (one run for both players)."""
    return [p.run_id for m in matches if m.played and m.mode == "coop" for p in m.players[:1] if p.run_id]


@dataclass(frozen=True)
class _CoopRun:
    """What a coop run reached: its stats when the run is known, else its match's summary."""

    best_hand: float
    hand: str | None  # the poker hand of the best hand
    ante: int
    round: int
    money: float
    boss_streak: int
    won: bool


def _coop_run(m: Match, run: RunSummary | None) -> _CoopRun:
    s = m.summary or {}
    seats = [_seat_summary(m, i) for i in range(len(m.players))]
    best_seat = max(seats, key=lambda p: _num(p.get("best_hand")), default={})
    seat_best = _num(best_seat.get("best_hand"))
    if run is None:
        return _CoopRun(best_hand=seat_best, hand=best_seat.get("best_hand_name"), ante=int(s.get("ante") or 0),
                        round=int(s.get("rounds") or 0), money=0.0, boss_streak=0, won=bool(s.get("run_won")))
    best = max(_num(run.stats.best_hand), seat_best)
    return _CoopRun(best_hand=best, hand=best_seat.get("best_hand_name") if seat_best >= best else None,
                    ante=max(run.stats.furthest_ante, run.progress.ante), round=max(run.stats.furthest_round,
                                                                                     run.progress.round),
                    money=_num(run.stats.most_money), boss_streak=run.stats.boss_streak, won=run.progress.won)


@dataclass
class _Row:
    """A board's candidate: a player (or a coop pair) and their value."""

    ids: tuple[str, ...]
    value: float = 0.0
    rounds: int = 0  # (coop_ante: the ties' breaker)
    hand: str | None = None
    played: int = 0
    at: datetime | None = None
    streak: int = 0  # (pvp_streak: the current one while counting)


def _coop_value(board: MultiplayerBoardName, c: _CoopRun) -> float:
    return {"coop_best_hand": c.best_hand, "coop_ante": float(c.ante), "coop_round": float(c.round),
            "coop_money": c.money, "coop_boss_streak": float(c.boss_streak), "coop_wins": 1.0 if c.won else 0.0}[board]


def _rows(matches: Sequence[Match], board: MultiplayerBoardName, runs: Mapping[str, RunSummary]) -> list[_Row]:
    coop = board in COOP_BOARDS
    rows: dict[tuple[str, ...], _Row] = {}
    for m in sorted((m for m in matches if m.played and m.mode == ("coop" if coop else "pvp")), key=_when):
        at = _when(m)
        if coop:
            if len(m.players) < 2:
                continue
            ids = tuple(sorted(p.id for p in m.players))
            r = rows.setdefault(ids, _Row(ids))
            r.played += 1
            c = _coop_run(m, runs.get(m.players[0].run_id or ""))
            v = _coop_value(board, c)
            if board == "coop_wins":
                if v:
                    r.value += 1
                    r.at = at
            elif (v, c.round if board == "coop_ante" else 0) > (r.value, r.rounds):
                r.value, r.at, r.hand = v, at, c.hand
                r.rounds = c.round if board == "coop_ante" else 0
            continue
        for seat, p in enumerate(m.players):
            r = rows.setdefault((p.id,), _Row((p.id,)))
            r.played += 1
            if board == "pvp_wins":
                if m.winner == seat:
                    r.value += 1
                    r.at = at
            elif board == "pvp_streak":
                r.streak = r.streak + 1 if m.winner == seat else 0
                if r.streak > r.value:
                    r.value, r.at = r.streak, at
            elif board == "pvp_biggest_hit":
                hit = int(_seat_summary(m, seat).get("biggest_hit") or 0)
                if hit > r.value:
                    r.value, r.at = hit, at
    return [r for r in rows.values() if r.value > 0 and r.at is not None]


def multiplayer_leaderboard(matches: Sequence[Match], board: MultiplayerBoardName, caller: str, limit: int = 50,
                            runs: Mapping[str, RunSummary] | None = None) -> MultiplayerLeaderboard:
    """The board's best entries (each player's, or each coop pair's), best first, ties sharing a
    rank and the earliest first; the caller's best entry in ``you``. ``runs``: the coop matches'
    runs by id (``coop_run_ids``), for their stats."""
    names: dict[str, str | None] = {}
    for m in sorted(matches, key=_when):  # (a player's latest name)
        for p in m.players:
            names[p.id] = p.name or names.get(p.id)
    rows = _rows(matches, board, runs or {})
    key = (lambda r: (r.value, r.rounds)) if board == "coop_ante" else (lambda r: (r.value, 0))
    rows.sort(key=lambda r: (-key(r)[0], -key(r)[1], r.at or datetime.min))

    def entry(r: _Row) -> MultiplayerLeaderboardEntry:
        rank = 1 + sum(1 for o in rows if key(o) > key(r))
        return MultiplayerLeaderboardEntry(
            rank=rank, you=caller in r.ids, value=score(r.value), played=r.played, achieved_at=r.at or datetime.min,
            rounds=r.rounds if board == "coop_ante" else None, hand=r.hand if board == "coop_best_hand" else None,
            players=[MultiplayerBoardPlayer(id=i, name=names.get(i), you=i == caller) for i in r.ids])

    mine = next((entry(r) for r in rows if caller in r.ids), None)
    return MultiplayerLeaderboard(board=board, players=len(rows), entries=[entry(r) for r in rows[:limit]], you=mine)


def multiplayer_global_stats(matches: Sequence[Match], now: datetime) -> MultiplayerGlobalStats:
    """Everyone's finished matches together."""
    played = [m for m in matches if m.played]
    players = {p.id for m in played for p in m.players}
    pvp: dict[str, Any] = {k: 0 for k in ("matches", "drawn", "left", "rounds", "best_ante", "damage", "biggest_hit")}
    coop: dict[str, Any] = {"matches": 0, "runs_won": 0, "best_ante": 0, "hands": 0, "chips": 0.0, "best_hand": 0.0,
                            "best_hand_name": None}
    antes: dict[str, list[int]] = {"pvp": [], "coop": []}
    decks: dict[str, Counter[str]] = {}
    today = now.date()
    days = {(today - timedelta(days=i)).isoformat(): Counter[str]() for i in range(DAYS)}
    for m in played:
        s = m.summary or {}
        ante = int(s.get("ante") or 0)
        mode = "coop" if m.mode == "coop" else "pvp"
        decks.setdefault(m.settings.deck, Counter())[mode] += 1
        day = _when(m).date().isoformat()
        if day in days:
            days[day][mode] += 1
        if ante:
            antes[mode].append(ante)
        seats = [_seat_summary(m, i) for i in range(len(m.players))]
        if mode == "pvp":
            pvp["matches"] += 1
            pvp["drawn"] += m.winner is None
            pvp["left"] += m.result == "left"
            pvp["rounds"] += int(s.get("rounds") or 0)
            pvp["best_ante"] = max(pvp["best_ante"], ante)
            for me in seats:
                pvp["damage"] += int(me.get("damage_taken") or 0)
                pvp["biggest_hit"] = max(pvp["biggest_hit"], int(me.get("biggest_hit") or 0))
        else:
            coop["matches"] += 1
            coop["runs_won"] += bool(s.get("run_won"))
            coop["best_ante"] = max(coop["best_ante"], ante)
            for me in seats:
                coop["hands"] += int(me.get("hands") or 0)
                coop["chips"] += _num(me.get("chips"))
                if _num(me.get("best_hand")) > coop["best_hand"]:
                    coop["best_hand"], coop["best_hand_name"] = _num(me.get("best_hand")), me.get("best_hand_name")

    def average(xs: list[int]) -> float:
        return round(sum(xs) / len(xs), 2) if xs else 0.0

    coop["chips"], coop["best_hand"] = score(coop["chips"]), score(coop["best_hand"])
    return MultiplayerGlobalStats(
        players=len(players), matches=len(played),
        pvp=PvPGlobalStats(**pvp, average_ante=average(antes["pvp"])),
        coop=CoopGlobalStats(**coop, average_ante=average(antes["coop"])),
        decks=sorted((MatchDeckCount(deck=d, pvp=c["pvp"], coop=c["coop"]) for d, c in decks.items()),
                     key=lambda d: (-(d.pvp + d.coop), d.deck)),
        days=[MatchDayCount(day=d, pvp=c["pvp"], coop=c["coop"]) for d, c in sorted(days.items())])
