"""Every storage keeps runs the same way and answers statistics the same way
(PostgreSQL's queries against the reference in application.statistics)."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from balatro_api.application import statistics
from balatro_api.domain import (
    Command,
    GameNotFound,
    GameSettings,
    JokerUsage,
    Phase,
    Progress,
    Run,
    RunStats,
    VersionConflict,
)
from balatro_api.infrastructure.persistence import InMemoryGameRepository

T0 = datetime(2026, 1, 1, tzinfo=UTC)
P = Progress(phase=Phase.BLIND_SELECT, ante=1, round=0, dollars=4, won=False)
STATS = RunStats(best_hand=1234, furthest_ante=3, furthest_round=8, most_money=27, boss_streak=1,
                 career={"c_hands_played": 9, "c_cards_played": 31, "c_dollars_earned": 45},
                 hands={"Pair": 4, "Flush": 2}, consumables={"c_mercury": 1}, vouchers={"v_grabber": 1},
                 jokers={"j_joker": JokerUsage(rounds=5), "j_hiker": JokerUsage(rounds=2, wins=1)})


@pytest.fixture(params=["memory", "postgres"])
def repo(request):
    return InMemoryGameRepository() if request.param == "memory" else request.getfixturevalue("pg")()


def make(run_id: str, at: datetime = T0, owner: str = "p1", **kw: object) -> Run:
    settings = kw.pop("settings", GameSettings(seed="ABC", deck="b_blue", stake=3, challenge=None, game_speed=2))
    return Run(id=run_id, settings=settings, engine_version="0.4.0", progress=P,  # type: ignore[arg-type]
               created_at=at, updated_at=at, owner=owner, **kw)  # type: ignore[arg-type]


def test_round_trip(repo):
    run = make("a", owner_name="Alice", settings=GameSettings(seed="ABC", seeded=True))
    repo.add(run)
    later = T0 + timedelta(minutes=1)
    run.record(Command({"cmd": "select_blind"}), Progress(Phase.PLAYING, 1, 1, 4, False), later)
    run.record(Command({"cmd": "play", "cards": [0, 2]}), Progress(Phase.PLAYING, 1, 1, 7.5, False), later,
               stats=STATS)
    run.record(Command({"cmd": "cheat", "dollars": 100}), Progress(Phase.PLAYING, 1, 1, 100, False), later,
               debug=True)
    repo.save(run, expected_version=0)
    got = repo.get("a")
    assert got == run
    assert got.commands[1].as_dict() == {"cmd": "play", "cards": [0, 2]}
    assert got.stats == STATS and got.debug and got.settings.seeded and got.owner_name == "Alice"
    assert [s.stats for s in repo.runs_of("p1")] == [STATS]


def test_huge_scores(repo):
    for i, best in enumerate((1e300, math.inf)):
        repo.add(make(f"r{i}", stats=RunStats(best_hand=best)))
        assert repo.get(f"r{i}").stats.best_hand == best


def test_optimistic_concurrency(repo):
    run = make("a")
    repo.add(run)
    first, second = repo.get("a"), repo.get("a")
    first.record(Command({"cmd": "select_blind"}), P, T0)
    repo.save(first, expected_version=0)
    second.record(Command({"cmd": "skip_blind"}), P, T0)
    with pytest.raises(VersionConflict):
        repo.save(second, expected_version=0)
    assert [c.as_dict() for c in repo.get("a").commands] == [{"cmd": "select_blind"}]


def test_list_and_delete(repo):
    for i in range(3):
        repo.add(make(f"r{i}", T0 + timedelta(minutes=i)))
    repo.add(make("theirs", T0 + timedelta(minutes=5), owner="p2"))
    repo.add(make("replayed", T0 + timedelta(minutes=6), replay=True))  # a bug report seen again: not listed
    assert repo.get("replayed").replay and not repo.get("r0").replay
    assert [s.id for s in repo.list("p1", 10, 0)] == ["r2", "r1", "r0"]
    assert [s.id for s in repo.list("p1", 1, 1)] == ["r1"]
    assert [(s.id, s.owner) for s in repo.list("p2", 10, 0)] == [("theirs", "p2")]
    assert [s.id for s in repo.runs_of("p1")] == ["r0", "r1", "r2", "replayed"]
    repo.delete("r1")
    with pytest.raises(GameNotFound):
        repo.get("r1")
    with pytest.raises(GameNotFound):
        repo.delete("r1")
    with pytest.raises(GameNotFound):
        repo.save(make("r1"), expected_version=0)


def test_postgres_survives_a_restart_and_migrates_once(pg):
    r = pg()
    run = make("a")
    r.add(run)
    run.record(Command({"cmd": "select_blind"}), P, T0)
    r.save(run, expected_version=0)
    assert pg().get("a") == run


# ------------------------------------------------------------ statistics
WON = Progress(Phase.SHOP, 9, 25, 30, True)
LOST = Progress(Phase.GAME_OVER, 4, 11, 0, False)


def population() -> list[Run]:
    """Players with ties, overflowed scores, decks and stakes, and runs that
    don't count (seeded, challenge, debug)."""
    runs = []

    def add(run_id: str, owner: str, minutes: int, progress: Progress = P, deck: str = "b_red", stake: int = 1,
            name: str | None = None, **stats: object) -> None:
        hand_stats = {k: v for k, v in stats.items() if k in ("best_hand", "furthest_ante", "furthest_round",
                                                             "most_money", "boss_streak")}
        flags = {k: v for k, v in stats.items() if k in ("seeded", "challenge")}
        run = Run(id=run_id, settings=GameSettings(seed="S", deck=deck, stake=stake, **flags),  # type: ignore[arg-type]
                  engine_version="0.4.0", progress=progress, created_at=T0 + timedelta(minutes=minutes),
                  updated_at=T0 + timedelta(minutes=minutes), owner=owner, owner_name=name,
                  debug=bool(stats.get("debug")),
                  stats=RunStats(**hand_stats, career={"c_hands_played": 10, "c_cards_played": 40,  # type: ignore[arg-type]
                                                       "c_dollars_earned": 50.5},
                                 hands={"Pair": 3, "High Card": 3, "Flush": 1},
                                 jokers={"j_joker": JokerUsage(rounds=3, wins=1 if progress.won else 0),
                                         "j_hiker": JokerUsage(rounds=0, losses=1)}))
        runs.append(run)

    add("a1", "alice", 1, WON, "b_red", 2, "Alice", best_hand=5000, furthest_ante=9, furthest_round=25,
        most_money=80, boss_streak=8)
    add("a2", "alice", 2, LOST, "b_blue", 1, "Alice", best_hand=9000, furthest_ante=4, furthest_round=11)
    add("a3", "alice", 3, WON, "b_red", 1, "Alice", best_hand=9000, furthest_ante=9)
    add("b1", "bob", 4, WON, "b_red", 2, "Bob", best_hand=9000, furthest_ante=9, most_money=80)
    add("b2", "bob", 5, P, "b_red", 2, "Bob", best_hand=math.inf, furthest_ante=1)
    add("c1", "carol", 6, LOST, "b_green", 5, None, best_hand=math.nan, furthest_ante=3)
    add("d1", "dave", 7, LOST, "b_red", 1, "Dave", best_hand=1e100, seeded=True)
    add("d2", "dave", 8, WON, "b_red", 1, "Dave", best_hand=2e100, challenge="c_omelette_1")
    add("d3", "dave", 9, WON, "b_red", 1, "Dave", best_hand=3e100, debug=True)
    add("e1", "erin", 10, P, "b_red", 1, "Erin")  # nothing reached yet: on no board
    return runs


BOARDS = ("best_hand", "highest_ante", "highest_round", "most_money", "boss_streak", "wins")


def summarize(page):
    return [(r.rank, r.owner, r.name, "nan" if math.isnan(r.value) else r.value, r.deck, r.stake, r.won, r.at)
            for r in page.rows], page.players


@pytest.mark.parametrize("board", BOARDS)
@pytest.mark.parametrize("deck, stake", [(None, None), ("b_red", None), (None, 2), ("b_red", 1), ("b_nope", None)])
def test_leaderboards_match_the_reference(repo, board, deck, stake):
    runs = population()
    for r in runs:
        repo.add(r)
    names = {r.owner: r.owner_name for r in runs}
    for limit, me in ((50, "alice"), (1, "carol"), (2, "erin")):
        want = statistics.leaderboard([r.summary() for r in runs], names, board, deck, stake, limit, me)
        assert summarize(repo.leaderboard(board, deck, stake, limit, me)) == summarize(want)


def test_leaderboard_rules(repo):
    for r in population():
        repo.add(r)
    page = repo.leaderboard("best_hand", None, None, 50, "alice")
    # nan (an overflowed score) > inf > numbers; dave's runs don't count; erin has no score
    assert [(r.rank, r.owner) for r in page.rows] == [(1, "carol"), (2, "bob"), (3, "alice")]
    assert page.rows[2].value == 9000 and page.rows[2].at == T0 + timedelta(minutes=2)  # the first time it was reached
    assert page.players == 3
    wins = repo.leaderboard("wins", None, None, 1, "bob")
    assert [(r.rank, r.owner, r.value) for r in wins.rows] == [(1, "alice", 2), (2, "bob", 1)]
    ante = repo.leaderboard("highest_ante", None, None, 50, "x")
    assert [(r.rank, r.owner) for r in ante.rows] == [(1, "alice"), (1, "bob"), (3, "carol")]  # ties share a rank


def test_global_stats_match_the_reference(repo):
    runs = population()
    for r in runs:
        repo.add(r)
    got = repo.global_stats()
    want = statistics.global_stats([r.summary() for r in runs])
    assert got == want
    assert (got.players, got.runs, got.won, got.lost) == (4, 7, 3, 2)  # dave's runs don't count
    assert got.best_hand == "nan" and got.hands_played == 70 and got.dollars_earned == 353.5
    assert [h.key for h in got.hands] == ["Pair", "High Card", "Flush"]  # ties: the better hand first


def test_an_unreachable_database_is_said_plainly():
    from balatro_api.infrastructure.persistence import DatabaseUnavailable, PostgresGameRepository

    with pytest.raises(DatabaseUnavailable, match="127.0.0.1:1/nowhere"):
        PostgresGameRepository("postgresql://u:secret@127.0.0.1:1/nowhere", connect_timeout=1)


def test_start_profile_and_players(repo):
    repo.add(make("legacy"))
    repo.add(make("tracked", start_profile={"unlocked": ["j_joker"], "discovered": []}))
    repo.add(make("tester", start_profile={"all": True}))
    assert repo.get("legacy").start_profile is None and repo.get("tracked").start_profile["unlocked"] == ["j_joker"]
    assert {s.id: s.tracks_progress for s in repo.runs_of("p1")} == {"legacy": False, "tracked": True, "tester": False}
    assert repo.player("nobody") is None
    p = repo.set_player("p9", "Nine", private=True)
    assert (p.name, p.private, p.all_unlocked) == ("Nine", True, False)
    p = repo.set_player("p9", None, all_unlocked=True)
    assert (p.name, p.private, p.all_unlocked) == ("Nine", True, True)
    assert repo.player("p9") == p


def test_pointers(repo):
    repo.add(make("r1"))
    assert repo.pointers("r1") == {}
    trace = {"v": 1, "e": [[0, "m", 1.5, 2.25], [120, "h", "hand", 4, 7]]}
    repo.save_pointer("r1", 0, trace)
    repo.save_pointer("r1", 3, {"v": 1, "e": []})
    repo.save_pointer("r1", 3, {"v": 1, "e": [[5, "d", 0, 0, 0]]})  # sent again: the last one stays
    assert repo.pointers("r1") == {0: trace, 3: {"v": 1, "e": [[5, "d", 0, 0, 0]]}}
    repo.delete("r1")
    assert repo.pointers("r1") == {}


# ------------------------------------------------------------------ matches
def test_matches(repo):
    from balatro_api.domain import Match, MatchNotFound, MatchPlayer, MatchSettings, MatchStatus

    m = Match(id="m1", code="ABCDEF", mode="pvp", host="p1", created_at=T0, updated_at=T0,
              settings=MatchSettings(deck="b_blue", stake=2, timer=60), players=[MatchPlayer(id="p1", name="Ann")])
    repo.add_match(m)
    assert repo.match_by_code("ABCDEF").id == "m1"
    assert repo.current_match("p1").id == "m1" and repo.current_match("p2") is None
    m.join(MatchPlayer(id="p2", name="Bob", game_speed=2), T0)
    m.start("SEED", ["r1", "r2"], T0 + timedelta(seconds=1))
    m.vote(0, 0, "skip", T0 + timedelta(seconds=2))
    m.set_wait(0, "vote:0", T0 + timedelta(seconds=2))
    repo.save_match(m, expected_version=0)
    with pytest.raises(VersionConflict):
        repo.save_match(m, expected_version=0)
    got = repo.get_match("m1")
    m.version = 1
    assert got == m and got.status is MatchStatus.PLAYING and got.players[1].run_id == "r2"
    assert repo.current_match("p2").id == "m1"
    with pytest.raises(MatchNotFound):
        repo.match_by_code("ABCDEF")  # (no longer in its lobby)
    got.finish(0, "hp", T0 + timedelta(seconds=3))
    repo.save_match(got, expected_version=1)
    assert repo.current_match("p1") is None
    with pytest.raises(MatchNotFound):
        repo.get_match("nope")


def test_finished_matches(repo):
    from balatro_api.domain import Match, MatchPlayer

    def played(i: int, result: str = "hp", status_players: tuple[str, ...] = ("p1", "p2")) -> Match:
        at = T0 + timedelta(minutes=i)
        m = Match(id=f"f{i}", code=f"CODE{i:02d}", mode="pvp", host="p1", created_at=at, updated_at=at,
                  players=[MatchPlayer(id=p, name=p) for p in status_players])
        repo.add_match(m)
        if result != "closed":
            m.start("SEED", ["r1", "r2"], at)
        m.finish(0, result, at)
        m.summary = {"ante": i, "rounds": 1, "players": []}
        m.rematch_id, m.kicked = "next", ["p9"]
        repo.save_match(m, expected_version=0)
        return m

    for i in range(3):
        played(i)
    played(3, "closed", ("p1",))
    lobby = Match(id="lobby", code="LOBBY1", mode="coop", host="p1", created_at=T0, updated_at=T0,
                  players=[MatchPlayer(id="p1")])
    repo.add_match(lobby)
    assert [m.id for m in repo.finished_matches("p1")] == ["f2", "f1", "f0"]  # (not the closed one, nor the lobby)
    assert [m.id for m in repo.finished_matches("p2", limit=2)] == ["f2", "f1"]
    assert [m.id for m in repo.finished_matches("p1", before=T0 + timedelta(minutes=2))] == ["f1", "f0"]
    assert repo.finished_matches("p3") == []
    got = repo.finished_matches("p1")[0]
    assert got.summary == {"ante": 2, "rounds": 1, "players": []} and got.rematch_id == "next" and got.kicked == ["p9"]


def test_match_runs_are_not_listed(repo):
    repo.add(make("solo"))
    repo.add(make("pvp", settings=GameSettings(seed="ABC", seeded=True, mode="pvp"), match_id="m1"))
    assert [r.id for r in repo.list("p1", 10, 0)] == ["solo"]
    got = repo.get("pvp")
    assert got.match_id == "m1" and got.settings.mode == "pvp" and not got.summary().counts
