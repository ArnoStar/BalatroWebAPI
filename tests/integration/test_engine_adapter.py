"""The engine adapter: runs played through the API are the engine's runs."""

from __future__ import annotations

import random
from dataclasses import asdict
from datetime import UTC, datetime

import pytest
from balatro import Game

from balatro_api.application.dto import PlayerAction
from balatro_api.domain import GameSettings, IllegalAction, InvalidGameSettings, Run
from balatro_api.infrastructure.engine import BalatroEngine
from tests.helpers import concrete

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def new_run(engine: BalatroEngine, run_id: str = "r", **kw: object) -> Run:
    settings = engine.check_settings(GameSettings(**{"seed": "TESTSEED", **kw}))  # type: ignore[arg-type]
    return Run(id=run_id, settings=settings, engine_version=engine.version, progress=engine.start(run_id, settings),
               created_at=NOW, updated_at=NOW)


def act(engine: BalatroEngine, run: Run, action: PlayerAction) -> None:
    out = engine.apply(run, action)
    run.record(out.command, out.progress, NOW)
    engine.commit(run, out)


def action_from(legal: dict) -> PlayerAction:
    a = dict(legal)
    for k in ("cards", "targets"):
        if a.get(k) is not None:
            a[k] = tuple(a[k])
    return PlayerAction(**a)


def play_randomly(engine: BalatroEngine, run: Run, steps: int, rnd: random.Random) -> None:
    for _ in range(steps):
        view = asdict(engine.view(run))
        if view["phase"] == "game_over":
            return
        for _ in range(10):
            a = concrete(view, rnd.choice(view["actions"]), rnd)
            if a is None:
                continue
            try:
                act(engine, run, action_from(a))
                break
            except IllegalAction:
                assert a["type"] in ("use", "pick"), a  # random targets may not fit the consumable


@pytest.mark.parametrize("seed,deck,stake", [("TESTSEED", "b_red", 1), ("API2PLAY", "b_plasma", 5),
                                             ("ZZZZ9999", "b_ghost", 8)])
def test_a_run_through_the_api_is_the_engines_run(seed, deck, stake):
    engine = BalatroEngine()
    run = new_run(engine, seed=seed, deck=deck, stake=stake)
    play_randomly(engine, run, 120, random.Random(seed))
    direct = Game(seed, deck=deck, stake=stake).start_run()
    for c in run.commands:
        direct.do(c.as_dict())
    with engine._game(run) as cached:
        assert cached.snapshot() == direct.snapshot()
    # a server that never saw the run rebuilds the same game from its commands
    fresh = BalatroEngine()
    assert fresh.view(run) == engine.view(run)


def test_an_illegal_action_changes_nothing():
    engine = BalatroEngine()
    run = new_run(engine)
    act(engine, run, PlayerAction(type="select_blind"))
    before = engine.view(run)
    hand = [c.id for c in before.hand]
    for bad in (PlayerAction(type="play", cards=tuple(hand[:6])), PlayerAction(type="play", cards=(99999,)),
                PlayerAction(type="cash_out"), PlayerAction(type="buy", card=hand[0]),
                PlayerAction(type="move", card=hand[0], to=99)):
        with pytest.raises(IllegalAction):
            engine.apply(run, bad)
        assert engine.view(run) == before


def test_settings_are_checked_and_normalized():
    engine = BalatroEngine()
    s = engine.check_settings(GameSettings(seed="abc0", deck="blue"))
    assert (s.seed, s.deck) == ("ABCO", "b_blue")
    s = engine.check_settings(GameSettings(seed="A", deck="b_blue", stake=5, challenge="c_omelette_1"))
    assert (s.deck, s.stake) == ("b_challenge", 1)
    for bad in (GameSettings(seed="A", deck="b_nope"), GameSettings(seed="A", challenge="c_nope")):
        with pytest.raises(InvalidGameSettings):
            engine.check_settings(bad)


def test_face_down_cards_are_hidden():
    engine = BalatroEngine()
    run = new_run(engine)
    for cmd in ({"cmd": "cheat", "boss": "bl_house"}, {"cmd": "select_blind"}, {"cmd": "cheat", "win": True},
                {"cmd": "cash_out"}, {"cmd": "end_shop"}, {"cmd": "select_blind"}, {"cmd": "cheat", "win": True},
                {"cmd": "cash_out"}, {"cmd": "end_shop"}, {"cmd": "select_blind"}):
        if cmd["cmd"] in ("cheat",):
            out = engine.apply_debug(run, cmd)
        else:
            out = engine.apply(run, PlayerAction(type=cmd["cmd"]))  # type: ignore[arg-type]
        run.record(out.command, out.progress, NOW)
        engine.commit(run, out)
    view = engine.view(run)
    assert view.blind is not None and view.blind.key == "bl_house"
    assert view.hand and all(c.face_down for c in view.hand)
    assert all(c.key is None and c.rank is None and c.suit is None for c in view.hand)
    # the hand can still be played, and the preview hides the hand as the game does
    ids = [c.id for c in view.hand[:2]]
    assert engine.preview_hand(run, ids).hidden
    act(engine, run, PlayerAction(type="play", cards=tuple(ids)))


def test_preview_and_cards_by_id():
    engine = BalatroEngine()
    run = new_run(engine)
    act(engine, run, PlayerAction(type="select_blind"))
    hand = engine.view(run).hand
    ids = [c.id for c in hand[:5]]
    p = engine.preview_hand(run, ids)
    assert p.hand == "Pair" and set(p.scoring) <= set(ids) and p.selected == ids
    act(engine, run, PlayerAction(type="play", cards=tuple(ids)))
    after = engine.view(run)
    assert not {c.id for c in after.hand} & set(ids)
    assert after.round_score == 56 and after.last_hand is not None and after.last_hand.hand == "Pair"


def test_feedback_events_follow_the_game():
    engine = BalatroEngine()
    run = new_run(engine)
    act(engine, run, PlayerAction(type="select_blind"))
    ids = [c.id for c in engine.view(run).hand[:5]]
    out = engine.apply(run, PlayerAction(type="play", cards=tuple(ids)))
    kinds = [e.type for e in out.events]
    assert kinds.index("card_moved") < kinds.index("card_text") < kinds.index("hand_scored")
    assert [e.t for e in out.events] == sorted(e.t for e in out.events)
    moved = [e for e in out.events if e.type == "card_moved"]
    assert {e.card for e in moved if e.to == "play"} == set(ids)


def test_stats_are_the_engines_profile():
    engine = BalatroEngine()
    run = new_run(engine)
    assert engine.run_stats(run).most_money == 4  # the starting money
    act(engine, run, PlayerAction(type="select_blind"))
    ids = [c.id for c in engine.view(run).hand[:5]]
    out = engine.apply(run, PlayerAction(type="play", cards=tuple(ids)))
    s = out.stats
    assert s.best_hand == 56 and s.furthest_round == 1 and s.furthest_ante == 1
    assert s.hands == {"Pair": 1}
    assert (s.career["c_hands_played"], s.career["c_cards_played"], s.career["c_rounds"]) == (1, 5, 1)
    # replaying the run gives the same stats
    run.record(out.command, out.progress, NOW, stats=s)
    engine.commit(run, out)
    assert BalatroEngine().run_stats(run) == s
    # a won round: joker usage, the boss streak needs a boss
    act_debug = engine.apply_debug(run, {"cmd": "add_joker", "key": "j_joker"})
    run.record(act_debug.command, act_debug.progress, NOW, debug=True)
    engine.commit(run, act_debug)
    won = engine.apply_debug(run, {"cmd": "cheat", "win": True})
    assert won.stats.jokers["j_joker"].rounds == 1 and won.stats.boss_streak == 0
