from datetime import UTC, datetime

import pytest

from balatro_api.domain import (
    Command,
    GameOver,
    GameSettings,
    InvalidGameSettings,
    Phase,
    Progress,
    Run,
    VersionConflict,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def run(phase: Phase = Phase.BLIND_SELECT) -> Run:
    return Run(id="r1", settings=GameSettings(seed="ABC"), engine_version="0", created_at=NOW, updated_at=NOW,
               progress=Progress(phase=phase, ante=1, round=0, dollars=4, won=False))


@pytest.mark.parametrize("kw", [dict(seed=""), dict(seed="TOOLONGSEED"), dict(seed="AB-C"), dict(seed="A", stake=0),
                                dict(seed="A", stake=9), dict(seed="A", game_speed=3)])
def test_invalid_settings(kw):
    with pytest.raises(InvalidGameSettings):
        GameSettings(**kw)


def test_version_is_the_number_of_commands():
    r = run()
    assert r.version == 0
    p = Progress(phase=Phase.PLAYING, ante=1, round=1, dollars=4, won=False)
    later = datetime(2026, 1, 2, tzinfo=UTC)
    r.record(Command({"cmd": "select_blind"}), p, later)
    assert r.version == 1 and r.progress == p and r.updated_at == later
    r.check_version(1)
    r.check_version(None)
    with pytest.raises(VersionConflict) as e:
        r.check_version(0)
    assert (e.value.expected, e.value.actual) == (0, 1)


def test_nothing_happens_after_game_over():
    r = run(Phase.GAME_OVER)
    with pytest.raises(GameOver):
        r.record(Command({"cmd": "select_blind"}), r.progress, NOW)
    assert r.version == 0


def test_match_votes_and_leaving():
    from datetime import UTC, datetime

    from balatro_api.domain import IllegalAction, Match, MatchFull, MatchPlayer, MatchStarted

    t = datetime(2026, 1, 1, tzinfo=UTC)
    m = Match(id="m", code="ABCDEF", mode="pvp", host="a", created_at=t, updated_at=t, players=[MatchPlayer(id="a")])
    assert m.join(MatchPlayer(id="b"), t) == 1 and m.join(MatchPlayer(id="b"), t) == 1
    with pytest.raises(MatchFull):
        m.join(MatchPlayer(id="c"), t)
    with pytest.raises(IllegalAction):
        m.vote(0, 0, "skip", t)  # (not started)
    m.start("SEED", ["ra", "rb"], t)
    with pytest.raises(MatchStarted):
        m.join(MatchPlayer(id="c"), t)
    m.vote(0, 0, "skip", t)
    m.vote(0, 0, "select", t)  # changed while the other hasn't chosen
    assert m.decision(0) is None
    m.vote(1, 0, "skip", t)
    assert m.decision(0) == "select"
    with pytest.raises(IllegalAction):
        m.vote(0, 0, "skip", t)  # decided
    m.vote(0, 1, "skip", t)
    m.vote(1, 1, "skip", t)
    assert m.decision(1) == "skip"
    m.leave("b", t)
    assert not m.active and m.winner == 0 and m.result == "left"


def test_dev_names_only_without_sign_in():
    from balatro_api.infrastructure.auth import AnonymousAuthenticator

    auth = AnonymousAuthenticator()
    assert auth.authenticate("dev:ann").id == "local:ann" and auth.authenticate("dev:ann").name == "ann"
    assert auth.authenticate("dev:no way").id == "local" and auth.authenticate(None).id == "local"
