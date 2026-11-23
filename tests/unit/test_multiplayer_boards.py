"""Everyone's multiplayer matches: the leaderboards and the statistics (application.multiplayer_boards)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from balatro_api.application.multiplayer_boards import coop_run_ids, multiplayer_global_stats, multiplayer_leaderboard
from balatro_api.domain import GameSettings, Match, MatchPlayer, MatchSettings, Phase, Progress, RunStats, RunSummary

NOW = datetime(2026, 11, 23, 12, tzinfo=UTC)


def match(i: int, mode: str, players: tuple[str, str], winner: int | None = None, result: str = "hp",
          summary: dict[str, Any] | None = None, deck: str = "b_red", days_ago: int = 0) -> Match:
    at = NOW - timedelta(days=days_ago) + timedelta(minutes=i)
    m = Match(id=f"m{i}", code=f"CODE{i:02d}", mode=mode, host=players[0], created_at=at, updated_at=at,
              settings=MatchSettings(deck=deck), players=[MatchPlayer(id=p, name=p.upper()) for p in players])
    m.start("SEED", [f"r{i}a", f"r{i}b"] if mode == "pvp" else [f"run{i}", f"run{i}"], at)
    m.finish(winner, result, at)
    m.summary = summary or {"ante": 1, "rounds": 1, "players": []}
    return m


def pvp(i: int, a: str, b: str, winner: int | None, hits: tuple[int, int] = (0, 0), **kw: Any) -> Match:
    players = [{"seat": s, "biggest_hit": hits[s], "damage_taken": hits[1 - s], "best_hand": 100} for s in (0, 1)]
    return match(i, "pvp", (a, b), winner, summary={"ante": 2, "rounds": 3, "players": players}, **kw)


def coop(i: int, a: str, b: str, ante: int, rounds: int, won: bool = False, best: tuple[float, float] = (0, 0),
         **kw: Any) -> Match:
    players = [{"seat": s, "best_hand": best[s], "best_hand_name": "Flush", "hands": 3, "chips": best[s]}
               for s in (0, 1)]
    return match(i, "coop", (a, b), None, "run_over", {"ante": ante, "rounds": rounds, "run_won": won,
                                                       "players": players}, **kw)


MATCHES = [
    pvp(1, "ann", "bob", 0, hits=(12, 4)),
    pvp(2, "ann", "bob", 0),
    pvp(3, "bob", "ann", 0, hits=(30, 0)),  # (bob wins: ann's streak ends at 2)
    pvp(4, "cy", "ann", 1, result="left"),
    pvp(5, "cy", "bob", None),  # a draw
    coop(6, "ann", "bob", 3, 9, best=(500, 2000)),
    coop(7, "bob", "ann", 5, 14, won=True),  # (the same pair, in the other seats)
    coop(8, "cy", "dee", 5, 15, best=(800, 0), deck="b_blue", days_ago=40),
]


def stats(i: int, best: float, ante: int, rnd: int, money: float, bosses: int, won: bool = False) -> RunSummary:
    at = NOW + timedelta(minutes=i)
    return RunSummary(id=f"run{i}", settings=GameSettings(seed="SEED", mode="coop", mode_rules=3), version=10,
                      progress=Progress(Phase.SHOP if won else Phase.GAME_OVER, ante, rnd, 0, won), created_at=at,
                      updated_at=at, stats=RunStats(best_hand=best, furthest_ante=ante, furthest_round=rnd,
                                                    most_money=money, boss_streak=bosses))


# the coop runs' stats (match 8's run isn't known: its summary stands in)
RUNS = {r.id: r for r in [stats(6, 2000, 3, 9, 40, 2), stats(7, 1500, 5, 14, 95, 4, won=True)]}


def board(name: str, caller: str = "ann", limit: int = 50) -> Any:
    return multiplayer_leaderboard(MATCHES, name, caller, limit, RUNS)  # type: ignore[arg-type]


def ids(entry: Any) -> list[str]:
    return [p.id for p in entry.players]


def test_pvp_boards():
    wins = board("pvp_wins")
    assert [(ids(e), e.value, e.rank, e.played) for e in wins.entries] == [(["ann"], 3, 1, 4), (["bob"], 1, 2, 4)]
    assert wins.you is not None and wins.you.you and wins.players == 2
    assert wins.entries[0].players[0].name == "ANN" and wins.entries[0].players[0].you
    assert [(ids(e), e.value) for e in board("pvp_streak").entries] == [(["ann"], 2), (["bob"], 1)]
    hits = board("pvp_biggest_hit")
    assert [(ids(e), e.value) for e in hits.entries] == [(["bob"], 30), (["ann"], 12)]


def test_coop_boards_rank_pairs():
    assert coop_run_ids(MATCHES) == ["run6", "run7", "run8"]
    best = board("coop_best_hand")
    # the pair's best hand: either player's, in any of their runs together
    assert [(ids(e), e.value, e.hand, e.played) for e in best.entries] == [
        (["ann", "bob"], 2000, "Flush", 2), (["cy", "dee"], 800, "Flush", 1)]
    assert best.players == 2 and best.you is not None and ids(best.you) == ["ann", "bob"]
    ante = board("coop_ante")
    # whatever their seats; ties on the ante broken by the rounds
    assert [(ids(e), e.value, e.rounds, e.rank) for e in ante.entries] == [
        (["cy", "dee"], 5, 15, 1), (["ann", "bob"], 5, 14, 2)]
    assert [(ids(e), e.value) for e in board("coop_round").entries] == [(["cy", "dee"], 15), (["ann", "bob"], 14)]
    # money and bosses in a row: the runs' own stats (an unknown run has none)
    assert [(ids(e), e.value) for e in board("coop_money").entries] == [(["ann", "bob"], 95)]
    assert [(ids(e), e.value) for e in board("coop_boss_streak").entries] == [(["ann", "bob"], 4)]
    wins = board("coop_wins")
    assert [(ids(e), e.value, e.played) for e in wins.entries] == [(["ann", "bob"], 1, 2)]


def test_the_caller_outside_the_top():
    b = board("coop_round", limit=1)
    assert len(b.entries) == 1 and b.you is not None and b.you.rank == 2 and ids(b.you) == ["ann", "bob"]
    assert board("pvp_wins", caller="dee").you is None


def test_without_the_runs_the_summaries_stand_in():
    b = multiplayer_leaderboard(MATCHES, "coop_best_hand", "ann")
    assert [(ids(e), e.value) for e in b.entries] == [(["ann", "bob"], 2000), (["cy", "dee"], 800)]
    assert multiplayer_leaderboard(MATCHES, "coop_wins", "ann").entries[0].value == 1
    assert multiplayer_leaderboard(MATCHES, "coop_money", "ann").entries == []


def test_global_stats():
    s = multiplayer_global_stats(MATCHES, NOW + timedelta(hours=1))
    assert s.players == 4 and s.matches == 8
    assert s.pvp.matches == 5 and s.pvp.drawn == 1 and s.pvp.left == 1 and s.pvp.rounds == 15
    assert s.pvp.biggest_hit == 30 and s.pvp.damage == 46 and s.pvp.best_ante == 2 and s.pvp.average_ante == 2
    assert s.coop.matches == 3 and s.coop.runs_won == 1 and s.coop.best_ante == 5 and s.coop.average_ante == 4.33
    assert s.coop.best_hand == 2000 and s.coop.best_hand_name == "Flush" and s.coop.hands == 18
    assert [(d.deck, d.pvp, d.coop) for d in s.decks] == [("b_red", 5, 2), ("b_blue", 0, 1)]
    assert len(s.days) == 30 and s.days[-1].day == "2026-11-23" and (s.days[-1].pvp, s.days[-1].coop) == (5, 2)
    assert sum(d.coop for d in s.days) == 2  # (the match 40 days ago is out of the chart)


def test_nothing_yet():
    s = multiplayer_global_stats([], NOW)
    assert s.players == 0 and s.matches == 0 and s.decks == [] and len(s.days) == 30
    assert multiplayer_leaderboard([], "pvp_wins", "ann").entries == []
