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
    opp = m["pvp"]["opponent"]
    assert len(opp["full_deck"]) == 52 and opp["deck_remaining"] == 44 and "id" not in opp["full_deck"][0]
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


# ------------------------------------------------------------------ coop
def coop_started(app: TestClient) -> tuple[dict, dict]:
    m = call(app, "ann", "POST", "/matches", 201, mode="coop", seed="TESTSEED")
    call(app, "bob", "POST", "/matches/join", code=m["code"])
    a = call(app, "ann", "POST", f"/matches/{m['id']}/start")
    b = call(app, "bob", "GET", f"/matches/{m['id']}")
    assert a["run_id"] == b["run_id"] and a["coop"]["turn"] == 0
    assert a["coop"]["your_turn"] and not b["coop"]["your_turn"]
    return a, b


def test_coop_is_one_run_played_in_turns(app):
    a, b = coop_started(app)
    run = a["run_id"]
    g_ann = call(app, "ann", "GET", f"/games/{run}")
    g_bob = call(app, "bob", "GET", f"/games/{run}")
    assert g_ann["settings"]["mode"] == "coop" and g_ann["joker_slots"] == 10 and g_ann["discards_left"] == 8
    assert g_ann["coop"]["seat"] == 0 and g_bob["coop"]["seat"] == 1
    assert "select_blind" in [x["type"] for x in g_ann["actions"]]
    assert "select_blind" not in [x["type"] for x in g_bob["actions"]]
    call(app, "cy", "GET", f"/games/{run}", 404)  # (not a player of it)
    act(app, "bob", run, 409, type="select_blind")  # (ann's turn)
    g = act(app, "ann", run, type="select_blind")["game"]
    hand = [c["id"] for c in g["hand"]]
    act(app, "bob", run, 409, type="play", cards=hand[:1])
    result = act(app, "ann", run, type="play", cards=hand[:5])
    assert result["game"]["coop"]["turn"] == 1 and any(e["type"] == "turn" for e in result["events"])
    assert not set(hand) & {c["id"] for c in result["game"]["hand"]}  # (bob's own cards now)
    # bob watches: the steps since his version, and ann's selection on her turns
    steps = call(app, "bob", "GET", f"/matches/{a['id']}/steps?since=0")
    assert steps["complete"] and [s["action"]["type"] for s in steps["steps"]] == ["select_blind", "play"]
    assert steps["steps"][1]["seat"] == 0 and steps["steps"][1]["events"]
    bob_hand = [c["id"] for c in result["game"]["hand"]]
    call(app, "bob", "PUT", f"/matches/{a['id']}/selection", 204, cards=bob_hand[:2])
    m = call(app, "ann", "GET", f"/matches/{a['id']}")
    assert m["coop"]["selection"] == bob_hand[:2] and m["coop"]["turn"] == 1
    # bob's turn: his play; then the round is lost when the hands are out
    g = act(app, "bob", run, type="play", cards=bob_hand[:1])["game"]
    while g["phase"] == "playing":
        who = "ann" if g["coop"]["turn"] == 0 else "bob"
        g = act(app, who, run, type="play", cards=[g["hand"][0]["id"]])["game"]
    m = call(app, "bob", "GET", f"/matches/{a['id']}")
    assert g["phase"] == "game_over" and m["status"] == "finished" and m["result"]["reason"] == "game_over"


def test_coop_shop_is_left_together(app):
    a, _ = coop_started(app)
    run = a["run_id"]
    act(app, "ann", run, type="select_blind")
    call(app, "ann", "POST", f"/games/{run}/debug", command={"cmd": "cheat", "win": True})
    act(app, "bob", run, type="cash_out")
    g = act(app, "ann", run, type="end_shop")["game"]
    assert g["phase"] == "shop" and g["coop"]["shop_votes"] == [0]
    assert "end_shop" not in [x["type"] for x in g["actions"]]
    g = act(app, "bob", run, type="end_shop")["game"]
    assert g["phase"] == "blind_select" and g["coop"]["turn"] == 0  # (no hand was played: still ann's turn)


# ------------------------------------------------------------------ after a match
def test_a_finished_match_has_its_summary_history_and_stats(app):
    a, b = started(app)
    vote(app, "ann", a["id"], "select")
    vote(app, "bob", a["id"], "select")
    act(app, "ann", a["run_id"], type="select_blind")
    act(app, "bob", b["run_id"], type="select_blind")
    call(app, "ann", "POST", f"/games/{a['run_id']}/debug", command={"cmd": "cheat", "win": True})
    lose_round(app, "bob", b["run_id"])
    call(app, "bob", "POST", f"/matches/{a['id']}/leave", 204)
    m = call(app, "ann", "GET", f"/matches/{a['id']}")
    s = m["summary"]
    assert s["ante"] == 1 and s["rounds"] == 1
    ann, bob = s["players"]
    assert ann["hp"] == 50 and bob["hp"] == 40 and bob["damage_taken"] == 10 and bob["rounds_lost"] == 1
    assert ann["damage_dealt"] == 0  # (a lost round's 10 hit points aren't the other player's doing)
    h = call(app, "ann", "GET", "/matches/history")
    assert [x["id"] for x in h["matches"]] == [a["id"]] and h["next_before"] is None
    entry = h["matches"][0]
    assert entry["result"]["you_won"] and entry["runs"] == [a["run_id"], b["run_id"]] and entry["summary"] == s
    st = call(app, "ann", "GET", "/matches/stats")
    assert st["pvp"]["played"] == 1 and st["pvp"]["won"] == 1 and st["pvp"]["opponent_left"] == 1
    assert st["pvp"]["streak"] == 1 and st["rivals"] == [{"id": "local:bob", "name": "bob", "played": 1, "won": 1,
                                                          "lost": 0, "best_ante": 0}]
    assert call(app, "bob", "GET", "/matches/stats")["pvp"]["gave_up"] == 1
    assert call(app, "cy", "GET", "/matches/history")["matches"] == []
    # a profile shows them
    profile = call(app, "cy", "GET", "/players/local:ann")
    assert profile["multiplayer"]["pvp"]["won"] == 1 and profile["matches"][0]["id"] == a["id"]
    # a closed lobby isn't a match played
    lobby = call(app, "ann", "POST", "/matches", 201, mode="pvp")
    call(app, "ann", "POST", f"/matches/{lobby['id']}/leave", 204)
    assert len(call(app, "ann", "GET", "/matches/history")["matches"]) == 1


def test_the_players_watch_each_others_runs_once_the_match_is_over(app):
    a, b = started(app)
    call(app, "ann", "GET", f"/games/{b['run_id']}/history", 404)  # (the match is being played)
    call(app, "bob", "POST", f"/matches/{a['id']}/leave", 204)
    assert call(app, "ann", "GET", f"/games/{b['run_id']}/history")["id"] == b["run_id"]
    assert call(app, "ann", "POST", f"/games/{b['run_id']}/watch", 201)["source"] == b["run_id"]
    call(app, "cy", "GET", f"/games/{b['run_id']}/history", 404)  # (others: finished runs only)


def test_rematch(app):
    a, _ = started(app)
    call(app, "ann", "POST", f"/matches/{a['id']}/rematch", 409)  # not over
    call(app, "bob", "POST", f"/matches/{a['id']}/leave", 204)
    nxt = call(app, "bob", "POST", f"/matches/{a['id']}/rematch")
    assert nxt["status"] == "lobby" and nxt["host"] and nxt["mode"] == "pvp"
    assert nxt["settings"] == {"deck": "b_red", "stake": 1, "seed": "TESTSEED", "timer": 120}
    old = call(app, "ann", "GET", f"/matches/{a['id']}")
    assert old["rematch"] == {"match_id": nxt["id"], "code": nxt["code"], "by_you": False, "open": True}
    joined = call(app, "ann", "POST", f"/matches/{a['id']}/rematch")
    assert joined["id"] == nxt["id"] and joined["seat"] == 1 and len(joined["players"]) == 2
    assert call(app, "bob", "POST", f"/matches/{a['id']}/rematch")["id"] == nxt["id"]  # (asking again: the same)
    call(app, "cy", "POST", f"/matches/{a['id']}/rematch", 404)


def test_the_host_kicks_a_player_from_the_lobby(app):
    m = call(app, "ann", "POST", "/matches", 201, mode="coop")
    call(app, "bob", "POST", "/matches/join", code=m["code"])
    call(app, "bob", "POST", f"/matches/{m['id']}/kick", 403, seat=0)  # not the host
    call(app, "ann", "POST", f"/matches/{m['id']}/kick", 409, seat=0)  # (themselves)
    kicked = call(app, "ann", "POST", f"/matches/{m['id']}/kick", seat=1)
    assert [p["name"] for p in kicked["players"]] == ["ann"]
    call(app, "bob", "GET", f"/matches/{m['id']}", 404)
    call(app, "bob", "POST", "/matches/join", 404, code=m["code"])  # (not again)
    call(app, "cy", "POST", "/matches/join", code=m["code"])


def test_emotes(app, clock):
    a, _ = started(app)
    call(app, "ann", "POST", f"/matches/{a['id']}/emote", 204, emote="good_luck")
    call(app, "ann", "POST", f"/matches/{a['id']}/emote", 204, emote="wow")  # (too soon: dropped)
    call(app, "ann", "POST", f"/matches/{a['id']}/emote", 422, emote="rude")
    call(app, "cy", "POST", f"/matches/{a['id']}/emote", 404, emote="gg")
    e = call(app, "bob", "GET", f"/matches/{a['id']}")["emotes"]
    assert [(x["seq"], x["seat"], x["emote"]) for x in e] == [(1, 0, "good_luck")]
    clock.t += timedelta(seconds=2)
    call(app, "bob", "POST", f"/matches/{a['id']}/emote", 204, emote="thanks")
    assert [x["emote"] for x in call(app, "ann", "GET", f"/matches/{a['id']}")["emotes"]] == ["good_luck", "thanks"]
    clock.t += timedelta(seconds=30)
    assert call(app, "ann", "GET", f"/matches/{a['id']}")["emotes"] == []


def test_coop_decks_and_summary(app):
    a, _ = coop_started(app)
    run = a["run_id"]
    decks = call(app, "bob", "GET", f"/games/{run}/coop/decks")["seats"]
    assert [len(d["full_deck"]) for d in decks] == [52, 52] and [len(d["remaining"]) for d in decks] == [52, 52]
    call(app, "cy", "GET", f"/games/{run}/coop/decks", 404)
    act(app, "ann", run, type="select_blind")
    g = call(app, "ann", "GET", f"/games/{run}")
    act(app, "ann", run, type="discard", cards=[g["hand"][0]["id"]])
    g = call(app, "ann", "GET", f"/games/{run}")
    act(app, "ann", run, type="play", cards=[c["id"] for c in g["hand"][:5]])
    decks = call(app, "ann", "GET", f"/games/{run}/coop/decks")["seats"]
    assert len(decks[0]["remaining"]) == 52 - 8 - 1 - 5 and len(decks[1]["remaining"]) == 44
    seats = call(app, "bob", "GET", f"/games/{run}")["coop"]["seats"]
    assert seats[0]["hands"] == 1 and seats[0]["discards"] == 1 and seats[0]["best_hand_name"]
    assert seats[1]["hands"] == 0
    assert "id" not in decks[0]["full_deck"][0]
    call(app, "bob", "POST", f"/matches/{a['id']}/leave", 204)
    s = call(app, "ann", "GET", f"/matches/{a['id']}")["summary"]
    assert s["ante"] == 1 and s["run_won"] is False
    ann, bob = s["players"]
    assert ann["hands"] == 1 and ann["discards"] == 1 and ann["chips"] == ann["best_hand"] > 0
    assert ann["best_hand_name"] and bob["hands"] == 0
    st = call(app, "bob", "GET", "/matches/stats")
    assert st["coop"]["played"] == 1 and st["partners"][0]["name"] == "ann" and st["pvp"]["played"] == 0
