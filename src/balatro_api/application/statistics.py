"""Statistics from runs: a player's profile stats, and the values the
leaderboards rank.  Pure functions over ``RunSummary`` (each run carries its
own ``RunStats``), so every storage gives the same answers."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta

from balatro_api.domain import Phase, RunSummary

from .dto import (
    CareerStats,
    DayActivity,
    DeckPopularity,
    DeckStats,
    GlobalStats,
    HighScores,
    JokerPopularity,
    JokerStats,
    LeaderboardName,
    Number,
    PlayerStats,
    RunCounts,
    Score,
    StakePopularity,
    StakeRecord,
    UsageCount,
)
from .ports import BoardPage, BoardRow

# the game's poker hands, best first (the order of its hand list): ties in
# "most played" go to the better hand
POKER_HANDS = ("Flush Five", "Flush House", "Five of a Kind", "Straight Flush", "Four of a Kind", "Full House",
               "Flush", "Straight", "Three of a Kind", "Two Pair", "Pair", "High Card")
ACTIVITY_DAYS = 30


def score(x: float) -> Score:
    """A score as JSON can carry it: whole numbers as integers, and "inf" or
    "nan" past the largest number (the game shows "naneinf")."""
    if math.isnan(x):
        return "nan"
    if math.isinf(x):
        return "inf" if x > 0 else "-inf"
    if float(x).is_integer() and abs(x) < 2 ** 53:
        return int(x)
    return x


def number(x: float) -> Number:
    return int(x) if float(x).is_integer() and abs(x) < 2 ** 53 else x


def rank_key(x: float) -> tuple[int, float]:
    """Leaderboard order (as PostgreSQL sorts numbers): nan, an overflowed
    score, above inf, above every number."""
    return (1, 0.0) if math.isnan(x) else (0, x)


def _desc(x: float) -> tuple[int, float]:
    k = rank_key(x)
    return -k[0], -k[1]


def reached(x: float) -> bool:
    return math.isnan(x) or x > 0


def outcome(r: RunSummary) -> str:
    if r.progress.won:
        return "won"
    return "lost" if r.progress.phase is Phase.GAME_OVER else "in_progress"


def board_value(r: RunSummary, board: LeaderboardName) -> float:
    s = r.stats
    return {"best_hand": s.best_hand, "highest_ante": float(s.furthest_ante),
            "highest_round": float(s.furthest_round), "most_money": s.most_money,
            "boss_streak": float(s.boss_streak), "wins": 1.0 if r.progress.won else 0.0}[board]


def _usage(counter: Counter[str], order: Sequence[str] = ()) -> list[UsageCount]:
    pos = {k: i for i, k in enumerate(order)}
    items = [(k, n) for k, n in counter.items() if n > 0]
    items.sort(key=lambda kv: (-kv[1], pos.get(kv[0], len(pos)), kv[0]))
    return [UsageCount(key=k, count=n) for k, n in items]


def _streaks(runs: Iterable[RunSummary]) -> tuple[int, int]:
    """(best, current) runs won in a row: a win adds one, a loss starts over."""
    best = current = 0
    for r in sorted(runs, key=lambda r: r.updated_at):
        o = outcome(r)
        if o == "won":
            current += 1
            best = max(best, current)
        elif o == "lost":
            current = 0
    return best, current


def player_stats(runs: Sequence[RunSummary], now: datetime) -> PlayerStats:
    counted = [r for r in runs if r.counts]
    outcomes = Counter(outcome(r) for r in counted)

    career: Counter[str] = Counter()
    hands: Counter[str] = Counter()
    consumables: Counter[str] = Counter()
    vouchers: Counter[str] = Counter()
    joker_rounds: Counter[str] = Counter()
    joker_runs: Counter[str] = Counter()
    joker_wins: Counter[str] = Counter()
    joker_losses: Counter[str] = Counter()
    joker_best: dict[str, int] = {}
    for r in counted:
        s = r.stats
        career.update(s.career)
        hands.update(s.hands)
        consumables.update(s.consumables)
        vouchers.update(s.vouchers)
        for key, u in s.jokers.items():
            joker_rounds[key] += u.rounds
            joker_runs[key] += 1 if u.rounds else 0
            joker_wins[key] += u.wins
            joker_losses[key] += u.losses
            if u.wins:
                joker_best[key] = max(joker_best.get(key, 0), r.settings.stake)

    best_streak, current_streak = _streaks(counted)
    hand_list = _usage(hands, POKER_HANDS)
    high = HighScores(
        best_hand=score(max((r.stats.best_hand for r in counted), key=rank_key, default=0)),
        highest_round=max((r.stats.furthest_round for r in counted), default=0),
        highest_ante=max((r.stats.furthest_ante for r in counted), default=0),
        most_money=number(max((r.stats.most_money for r in counted), default=0)),
        boss_streak=max((r.stats.boss_streak for r in counted), default=0),
        best_win_streak=best_streak, current_win_streak=current_streak,
        most_played_hand=hand_list[0] if hand_list else None)

    def c(key: str) -> int:
        return int(career[key])

    career_view = CareerStats(
        wins=c("c_wins"), losses=c("c_losses"), rounds=c("c_rounds"), hands_played=c("c_hands_played"),
        cards_played=c("c_cards_played"), face_cards_played=c("c_face_cards_played"),
        cards_discarded=c("c_cards_discarded"), dollars_earned=number(career["c_dollars_earned"]),
        shop_dollars_spent=number(career["c_shop_dollars_spent"]), shop_rerolls=c("c_shop_rerolls"),
        jokers_sold=c("c_jokers_sold"), cards_sold=c("c_cards_sold"), tarots_bought=c("c_tarots_bought"),
        planets_bought=c("c_planets_bought"), playing_cards_bought=c("c_playing_cards_bought"),
        vouchers_bought=c("c_vouchers_bought"), tarot_readings_used=c("c_tarot_reading_used"),
        planetariums_used=c("c_planetarium_used"))

    jokers = [JokerStats(key=k, runs=joker_runs[k], rounds=joker_rounds[k], wins=joker_wins[k],
                         losses=joker_losses[k], best_stake_won=joker_best.get(k))
              for k in set(joker_rounds) | set(joker_wins) | set(joker_losses)]
    jokers.sort(key=lambda j: (-j.rounds, -j.wins, j.key))

    by_deck: dict[str, dict[int, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
    for r in counted:
        by_deck[r.settings.deck][r.settings.stake][outcome(r)] += 1
    decks = []
    for deck, stakes in by_deck.items():
        records = [StakeRecord(stake=st, runs=sum(n.values()), wins=n["won"], losses=n["lost"])
                   for st, n in sorted(stakes.items())]
        won_stakes = [s.stake for s in records if s.wins]
        decks.append(DeckStats(deck=deck, runs=sum(s.runs for s in records), wins=sum(s.wins for s in records),
                               losses=sum(s.losses for s in records),
                               best_stake_won=max(won_stakes) if won_stakes else None, stakes=records))
    decks.sort(key=lambda d: (-d.runs, d.deck))

    today = now.date()
    days = {(today - timedelta(days=i)).isoformat(): Counter[str]() for i in range(ACTIVITY_DAYS)}
    for r in counted:
        day = days.get(r.created_at.date().isoformat())
        if day is not None:
            day["runs"] += 1
            day["wins"] += 1 if r.progress.won else 0
    activity = [DayActivity(date=d, runs=n["runs"], wins=n["wins"]) for d, n in sorted(days.items())]

    return PlayerStats(
        runs=RunCounts(total=len(runs), counted=len(counted), won=outcomes["won"], lost=outcomes["lost"],
                       in_progress=outcomes["in_progress"]),
        high_scores=high, career=career_view, hands=hand_list, jokers=jokers, consumables=_usage(consumables),
        vouchers=_usage(vouchers), decks=decks, activity=activity)


# ------------------------------------------------------------ everyone
# (the in-memory storage uses these; a database answers the same with queries)

def leaderboard(runs: Iterable[RunSummary], names: Mapping[str, str | None], board: LeaderboardName,
                deck: str | None, stake: int | None, limit: int, owner: str) -> BoardPage:
    counted = [r for r in runs if r.counts and (deck is None or r.settings.deck == deck)
               and (stake is None or r.settings.stake == stake)]
    best: dict[str, BoardRow] = {}
    if board == "wins":
        for r in counted:
            if r.progress.won:
                prev = best.get(r.owner)
                best[r.owner] = BoardRow(rank=0, owner=r.owner, name=None, value=(prev.value if prev else 0) + 1,
                                         deck=None, stake=None, won=None,
                                         at=max(prev.at, r.updated_at) if prev else r.updated_at)
    else:
        for r in sorted(counted, key=lambda r: r.updated_at):
            v = board_value(r, board)
            prev = best.get(r.owner)
            if reached(v) and (prev is None or rank_key(v) > rank_key(prev.value)):
                best[r.owner] = BoardRow(rank=0, owner=r.owner, name=None, value=v, deck=r.settings.deck,
                                         stake=r.settings.stake, won=r.progress.won, at=r.updated_at)
    ordered = sorted(best.values(), key=lambda b: (_desc(b.value), b.at))
    rows = []
    for i, b in enumerate(ordered):
        rank = 1 + sum(1 for o in ordered if rank_key(o.value) > rank_key(b.value))
        if i < limit or b.owner == owner:
            rows.append(BoardRow(rank=rank, owner=b.owner, name=names.get(b.owner), value=b.value, deck=b.deck,
                                 stake=b.stake, won=b.won, at=b.at))
    return BoardPage(rows=rows, players=len(ordered))


def global_stats(runs: Iterable[RunSummary]) -> GlobalStats:
    counted = [r for r in runs if r.counts]
    career: Counter[str] = Counter()
    hands: Counter[str] = Counter()
    joker_runs: Counter[str] = Counter()
    joker_win_runs: Counter[str] = Counter()
    decks: dict[str, Counter[str]] = defaultdict(Counter)
    stakes: dict[int, Counter[str]] = defaultdict(Counter)
    for r in counted:
        career.update(r.stats.career)
        hands.update(r.stats.hands)
        for key, u in r.stats.jokers.items():
            joker_runs[key] += 1 if u.rounds else 0
            joker_win_runs[key] += 1 if r.progress.won and u.wins else 0
        for c in (decks[r.settings.deck], stakes[r.settings.stake]):
            c["runs"] += 1
            c["wins"] += 1 if r.progress.won else 0
    jokers = sorted(((k, joker_runs[k], joker_win_runs[k]) for k in set(joker_runs) | set(joker_win_runs)
                     if joker_runs[k] or joker_win_runs[k]), key=lambda j: (-j[1], -j[2], j[0]))[:20]
    outcomes = Counter(outcome(r) for r in counted)
    return GlobalStats(
        players=len({r.owner for r in counted}), runs=len(counted), won=outcomes["won"], lost=outcomes["lost"],
        hands_played=int(career["c_hands_played"]), cards_played=int(career["c_cards_played"]),
        dollars_earned=number(career["c_dollars_earned"]),
        best_hand=score(max((r.stats.best_hand for r in counted), key=rank_key, default=0)),
        highest_ante=max((r.stats.furthest_ante for r in counted), default=0),
        decks=sorted((DeckPopularity(deck=d, runs=c["runs"], wins=c["wins"]) for d, c in decks.items()),
                     key=lambda d: (-d.runs, d.deck)),
        stakes=[StakePopularity(stake=st, runs=c["runs"], wins=c["wins"]) for st, c in sorted(stakes.items())],
        jokers=[JokerPopularity(key=k, runs=n, win_runs=w) for k, n, w in jokers],
        hands=_usage(hands, POKER_HANDS))
