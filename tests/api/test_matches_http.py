"""Multiplayer matches over HTTP: the lobby, then PvP on two runs (votes, waits, the timer, hit points)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from balatro_api.bootstrap import build_use_cases
from balatro_api.config import Settings
from balatro_api.presentation.http import create_app

API = "/api/v1"


class Clock:
    def __init__(self) -> None:
        self.t = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self.t


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def app(clock: Clock) -> TestClient:
    # (sign-in off: "dev:<name>" tokens name the players)
    return TestClient(create_app(build_use_cases(Settings(database="memory", debug_commands=True), clock=clock)))


def as_(name: str) -> dict[str, str]:
    return {"Authorization": f"Bearer dev:{name}"}


def call(app: TestClient, who: str, method: str, path: str, status: int = 200, **body: object) -> dict:
    r = app.request(method, f"{API}{path}", headers=as_(who), json=body if body else None)
    assert r.status_code == status, r.text
    return r.json() if r.content else {}


def started(app: TestClient, **settings: object) -> tuple[dict, dict]:
    m = call(app, "ann", "POST", "/matches", 201, mode="pvp", seed="TESTSEED", **settings)
    assert m["status"] == "lobby" and m["host"] and len(m["code"]) == 6
    joined = call(app, "bob", "POST", "/matches/join", code=m["code"].lower())
    assert joined["seat"] == 1 and [p["name"] for p in joined["players"]] == ["ann", "bob"]
    call(app, "bob", "POST", f"/matches/{m['id']}/start", 403)  # only the host starts it
    m = call(app, "ann", "POST", f"/matches/{m['id']}/start")
    assert m["status"] == "playing" and m["pvp"]["hp"] == [50, 50]
    return m, call(app, "bob", "GET", f"/matches/{m['id']}")


def act(app: TestClient, who: str, run_id: str, status: int = 200, **action: object) -> dict:
    return call(app, who, "POST", f"/games/{run_id}/actions", status, **action)


def vote(app: TestClient, who: str, match_id: str, choice: str) -> dict:
    return call(app, who, "POST", f"/matches/{match_id}/vote", choice=choice)


def lose_round(app: TestClient, who: str, run_id: str) -> dict:
    game = call(app, who, "GET", f"/games/{run_id}")
    while game["phase"] == "playing":
        game = act(app, who, run_id, type="play", cards=[game["hand"][0]["id"]])["game"]
    return game


def test_the_lobby(app):
    m = call(app, "ann", "POST", "/matches", 201, mode="pvp")
    assert call(app, "ann", "GET", "/matches/current")["id"] == m["id"]
    call(app, "cy", "GET", f"/matches/{m['id']}", 404)  # not a player of it
    call(app, "ann", "POST", f"/matches/{m['id']}/start", 409)  # alone
    call(app, "bob", "POST", "/matches/join", code=m["code"])
    call(app, "cy", "POST", "/matches/join", 409, code=m["code"])  # full
    changed = call(app, "ann", "PUT", f"/matches/{m['id']}/settings", deck="b_blue", stake=3, timer=60)
    assert changed["settings"] == {"deck": "b_blue", "stake": 3, "seed": None, "timer": 60}
    call(app, "bob", "PUT", f"/matches/{m['id']}/settings", 403, deck="b_red")
    call(app, "bob", "POST", f"/matches/{m['id']}/leave", 204)
    assert [p["name"] for p in call(app, "ann", "GET", f"/matches/{m['id']}")["players"]] == ["ann"]
    call(app, "ann", "POST", f"/matches/{m['id']}/leave", 204)  # the host closes it
    assert app.get(f"{API}/matches/current", headers=as_("ann")).status_code == 204
    call(app, "bob", "POST", "/matches/join", 404, code=m["code"])


def test_pvp_runs_are_the_same_seed_and_not_listed(app):
    a, b = started(app, deck="b_blue")
    ra = call(app, "ann", "GET", f"/games/{a['run_id']}")
    rb = call(app, "bob", "GET", f"/games/{b['run_id']}")
    assert ra["settings"]["seed"] == rb["settings"]["seed"] == "TESTSEED"
    assert ra["settings"]["mode"] == "pvp" and ra["settings"]["deck"] == "b_blue"
    call(app, "bob", "GET", f"/games/{a['run_id']}", 404)  # one's own run only
    assert call(app, "ann", "GET", "/games") == []
    call(app, "ann", "DELETE", f"/games/{a['run_id']}", 409)
    # playing a match: another one can't be made or joined
    call(app, "ann", "POST", "/matches", 409, mode="pvp")


def test_blind_votes(app):
    a, b = started(app)
    act(app, "ann", a["run_id"], 409, type="select_blind")  # both choose first
    m = vote(app, "ann", a["id"], "skip")
    assert m["pvp"]["vote"] == {"index": 0, "yours": "skip", "theirs": None, "decision": None}
    assert m["pvp"]["waiting"] == "vote" and m["pvp"]["deadline"] is not None
    m = vote(app, "bob", a["id"], "select")
    assert m["pvp"]["vote"]["decision"] == "select" and m["pvp"]["vote"]["theirs"] == "skip"
    act(app, "ann", a["run_id"], 409, type="skip_blind")  # not both skipped
    assert act(app, "ann", a["run_id"], type="select_blind")["game"]["phase"] == "playing"
    # both skip: skipped
    act(app, "bob", b["run_id"], type="select_blind")
    for who, run in (("ann", a["run_id"]), ("bob", b["run_id"])):
        call(app, who, "POST", f"/games/{run}/debug", command={"cmd": "cheat", "win": True})
    for who, run in (("ann", a["run_id"]), ("bob", b["run_id"])):
        act(app, who, run, type="cash_out")
        act(app, who, run, type="end_shop")
    vote(app, "ann", a["id"], "skip")
    vote(app, "bob", a["id"], "skip")
    assert act(app, "ann", a["run_id"], type="skip_blind")["game"]["blind_select"]["on_deck"] == "Boss"
    m = call(app, "ann", "GET", f"/matches/{a['id']}")
    assert m["pvp"]["blind_index"] == 2  # (bob hasn't skipped yet: the boss's vote is open anyway)
    assert m["pvp"]["vote"] == {"index": 2, "yours": None, "theirs": None, "decision": None}
    act(app, "bob", b["run_id"], type="skip_blind")
    m = call(app, "ann", "GET", f"/matches/{a['id']}")
    assert [r["skipped"] for r in m["pvp"]["rounds"]] == [[False, False], [True, True]]
    call(app, "ann", "POST", f"/matches/{a['id']}/vote", 409, choice="skip")  # a boss can't be skipped


def test_rounds_cost_hit_points(app):
    a, b = started(app)
    vote(app, "ann", a["id"], "select")
    vote(app, "bob", a["id"], "select")
    act(app, "ann", a["run_id"], type="select_blind")
    act(app, "bob", b["run_id"], type="select_blind")
    call(app, "ann", "POST", f"/games/{a['run_id']}/debug", command={"cmd": "cheat", "win": True})
    act(app, "ann", a["run_id"], 409, type="cash_out")  # bob still plays the round
    m = call(app, "ann", "GET", f"/matches/{a['id']}")
    assert m["pvp"]["waiting"] == "round" and not m["pvp"]["can_cash_out"]
    assert m["pvp"]["opponent"]["phase"] == "playing" and m["pvp"]["opponent"]["blind"]["key"] == "bl_small"
    assert call(app, "bob", "GET", f"/matches/{a['id']}")["pvp"]["opponent_waiting"] == "round"
    game = lose_round(app, "bob", b["run_id"])
    assert game["phase"] == "round_eval"  # a lost round doesn't end the run
    m = call(app, "ann", "GET", f"/matches/{a['id']}")
    assert m["pvp"]["hp"] == [50, 40] and m["pvp"]["can_cash_out"] and m["pvp"]["waiting"] is None
    r = m["pvp"]["rounds"][0]
    assert r["lost"] == [False, True] and r["damage"] == [0, 10] and r["target"] == [300, 300]
    act(app, "ann", a["run_id"], type="cash_out")


def test_the_timer_moves_a_late_player_on(app, clock):
    a, b = started(app, timer=60)
    vote(app, "ann", a["id"], "select")
    clock.t += timedelta(seconds=61)
    m = call(app, "ann", "GET", f"/matches/{a['id']}")  # bob didn't choose: he plays the blind
    assert m["pvp"]["vote"]["decision"] == "select"
    act(app, "ann", a["run_id"], type="select_blind")
    call(app, "ann", "POST", f"/games/{a['run_id']}/debug", command={"cmd": "cheat", "win": True})
    clock.t += timedelta(seconds=30)
    assert call(app, "ann", "GET", f"/matches/{a['id']}")["pvp"]["waiting"] == "round"
    clock.t += timedelta(seconds=31)
    m = call(app, "ann", "GET", f"/matches/{a['id']}")  # bob's round is lost for him
    assert m["pvp"]["hp"] == [50, 40] and m["pvp"]["can_cash_out"]
    bob = call(app, "bob", "GET", f"/matches/{a['id']}")
    assert bob["run_version"] > b["run_version"]
    assert call(app, "bob", "GET", f"/games/{b['run_id']}")["phase"] == "round_eval"
    # ann goes on to the next blind; bob is moved through the cash out and the shop, then plays it
    act(app, "ann", a["run_id"], type="cash_out")
    act(app, "ann", a["run_id"], type="end_shop")
    vote(app, "ann", a["id"], "skip")
    clock.t += timedelta(seconds=61)
    m = call(app, "ann", "GET", f"/matches/{a['id']}")
    assert m["pvp"]["vote"] == {"index": 1, "yours": "skip", "theirs": "select", "decision": "select"}
    assert call(app, "bob", "GET", f"/games/{b['run_id']}")["phase"] == "blind_select"


def test_leaving_loses(app):
    a, _ = started(app)
    call(app, "bob", "POST", f"/matches/{a['id']}/leave", 204)
    m = call(app, "ann", "GET", f"/matches/{a['id']}")
    assert m["status"] == "finished" and m["result"] == {"winner": 0, "you_won": True, "reason": "left"}
    assert not call(app, "bob", "GET", f"/matches/{a['id']}")["result"]["you_won"]
    # (the runs are free now)
    act(app, "ann", a["run_id"], type="select_blind")


def test_knocked_out(app):
    a, b = started(app)
    for _ in range(5):  # bob loses five rounds: 50 hit points
        m = call(app, "ann", "GET", f"/matches/{a['id']}")
        if m["status"] == "finished":
            break
        vote(app, "ann", a["id"], "select")
        vote(app, "bob", a["id"], "select")
        act(app, "ann", a["run_id"], type="select_blind")
        act(app, "bob", b["run_id"], type="select_blind")
        call(app, "ann", "POST", f"/games/{a['run_id']}/debug", command={"cmd": "cheat", "win": True})
        lose_round(app, "bob", b["run_id"])
        for who, run in (("ann", a["run_id"]), ("bob", b["run_id"])):
            if call(app, who, "GET", f"/matches/{a['id']}")["status"] == "finished":
                break
            act(app, who, run, type="cash_out")
            act(app, who, run, type="end_shop")
    m = call(app, "bob", "GET", f"/matches/{a['id']}")
    assert m["status"] == "finished" and m["pvp"]["hp"] == [50, 0]
    assert m["result"] == {"winner": 0, "you_won": False, "reason": "hp"}
