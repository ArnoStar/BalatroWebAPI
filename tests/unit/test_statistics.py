"""A player's statistics from their runs (application.statistics)."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from balatro_api.application.statistics import player_stats, score
from balatro_api.domain import GameSettings, JokerUsage, Phase, Progress, RunStats, RunSummary

NOW = datetime(2026, 3, 31, 12, tzinfo=UTC)
WON = Progress(Phase.SHOP, 9, 25, 30, True)
LOST = Progress(Phase.GAME_OVER, 3, 8, 0, False)
GOING = Progress(Phase.PLAYING, 2, 5, 10, False)


def run(i: int, progress: Progress, deck: str = "b_red", stake: int = 1, days_ago: int = 0, **kw: object) -> RunSummary:
    flags = {k: kw.pop(k) for k in ("seeded", "challenge") if k in kw}
    debug = bool(kw.pop("debug", False))
    at = NOW - timedelta(days=days_ago) + timedelta(minutes=i)
    return RunSummary(id=f"r{i}", settings=GameSettings(seed="S", deck=deck, stake=stake, **flags),  # type: ignore[arg-type]
                      progress=progress, version=1, created_at=at, updated_at=at, stats=RunStats(**kw),  # type: ignore[arg-type]
                      debug=debug)


def test_counts_like_the_game():
    runs = [run(1, WON, best_hand=500, career={"c_hands_played": 4}),
            run(2, LOST, best_hand=100, career={"c_hands_played": 6}),
            run(3, GOING),
            run(4, WON, best_hand=9e99, seeded=True, career={"c_hands_played": 100}),
            run(5, WON, best_hand=9e99, challenge="c_omelette_1"),
            run(6, WON, best_hand=9e99, debug=True)]
    s = player_stats(runs, NOW)
    assert (s.runs.total, s.runs.counted, s.runs.won, s.runs.lost, s.runs.in_progress) == (6, 3, 1, 1, 1)
    assert s.high_scores.best_hand == 500
    assert s.career.hands_played == 10


def test_high_scores_and_streaks():
    runs = [run(1, WON), run(2, WON), run(3, GOING), run(4, WON), run(5, LOST), run(6, WON, best_hand=math.inf,
                                                                                  furthest_ante=9, boss_streak=3,
                                                                                  most_money=88.5)]
    h = player_stats(runs, NOW).high_scores
    assert (h.best_win_streak, h.current_win_streak) == (3, 1)  # a run still going doesn't break a streak
    assert (h.best_hand, h.highest_ante, h.boss_streak, h.most_money) == ("inf", 9, 3, 88.5)


def test_usage_decks_and_activity():
    runs = [run(1, WON, deck="b_red", stake=3, hands={"Pair": 2, "Flush": 2},
                jokers={"j_joker": JokerUsage(rounds=4, wins=1)}, consumables={"c_mars": 2}),
            run(2, LOST, deck="b_red", stake=1, hands={"Pair": 1}, jokers={"j_joker": JokerUsage(rounds=1, losses=1),
                                                                           "j_hiker": JokerUsage(losses=1)}),
            run(3, WON, deck="b_blue", stake=1, days_ago=40)]
    s = player_stats(runs, NOW)
    assert [(h.key, h.count) for h in s.hands] == [("Pair", 3), ("Flush", 2)]
    assert s.high_scores.most_played_hand is not None and s.high_scores.most_played_hand.key == "Pair"
    joker = s.jokers[0]
    assert (joker.key, joker.runs, joker.rounds, joker.wins, joker.losses, joker.best_stake_won) == \
        ("j_joker", 2, 5, 1, 1, 3)
    assert [(j.key, j.runs, j.losses, j.best_stake_won) for j in s.jokers[1:]] == [("j_hiker", 0, 1, None)]
    red = s.decks[0]
    assert (red.deck, red.runs, red.wins, red.losses, red.best_stake_won) == ("b_red", 2, 1, 1, 3)
    assert [(x.stake, x.runs, x.wins, x.losses) for x in red.stakes] == [(1, 1, 0, 1), (3, 1, 1, 0)]
    assert len(s.activity) == 30 and s.activity[-1].date == "2026-03-31"
    assert (s.activity[-1].runs, s.activity[-1].wins) == (2, 1)  # the run of 40 days ago is out of the window
    assert sum(d.runs for d in s.activity) == 2


def test_most_played_hand_ties_go_to_the_better_hand():
    s = player_stats([run(1, GOING, hands={"High Card": 2, "Straight": 2})], NOW)
    assert s.high_scores.most_played_hand is not None and s.high_scores.most_played_hand.key == "Straight"


def test_scores_as_json_carries_them():
    assert (score(12.0), score(1e300), score(math.inf), score(math.nan)) == (12, 1e300, "inf", "nan")


def test_no_runs():
    s = player_stats([], NOW)
    assert s.runs.total == 0 and s.high_scores.best_hand == 0 and s.high_scores.most_played_hand is None
