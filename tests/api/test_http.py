"""The HTTP API as a front end uses it."""

from __future__ import annotations

import random

from fastapi.testclient import TestClient

from balatro_api.bootstrap import build_use_cases
from balatro_api.config import Settings
from balatro_api.presentation.http import create_app
from tests.helpers import concrete

API = "/api/v1"


def new_game(client: TestClient, **body: object) -> dict:
    r = client.post(f"{API}/games", json={"seed": "TESTSEED", **body})
    assert r.status_code == 201, r.text
    assert r.headers["location"] == f"{API}/games/{r.json()['id']}"
    return r.json()


def act(client: TestClient, game: dict, **action: object) -> dict:
    r = client.post(f"{API}/games/{game['id']}/actions", json={**action, "expected_version": game["version"]})
    assert r.status_code == 200, r.text
    return r.json()


def test_health_and_catalog(client):
    assert client.get(f"{API}/health").json()["status"] == "ok"
    r = client.get(f"{API}/catalog")
    cat = r.json()
    assert len(cat["jokers"]) == 150 and len(cat["decks"]) == 15 and len(cat["stakes"]) == 8
    joker = next(j for j in cat["jokers"] if j["key"] == "j_joker")
    assert joker["name"] == "Joker" and joker["sprite"]["atlas"] == "Joker" and joker["config"] == {"mult": 4}
    assert cat["atlases"]["Joker"]["file"] == "Jokers.png"
    assert cat["challenge_deck"]["key"] == "b_challenge" and cat["challenge_deck"]["sprite"]["pos"] == {"x": 0, "y": 4}
    again = client.get(f"{API}/catalog", headers={"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304


def test_a_round(client):
    game = new_game(client)
    assert game["phase"] == "blind_select" and game["version"] == 0
    assert [a["type"] for a in game["actions"]][:2] == ["select_blind", "skip_blind"]
    game = act(client, game, type="select_blind")["game"]
    assert game["phase"] == "playing" and len(game["hand"]) == 8 and game["blind"]["key"] == "bl_small"
    ids = [c["id"] for c in game["hand"][:5]]
    preview = client.post(f"{API}/games/{game['id']}/preview", json={"cards": ids}).json()
    assert preview["hand"] == "Pair"
    result = act(client, game, type="play", cards=ids)
    assert result["game"]["round_score"] == 56
    scored = [e for e in result["events"] if e["type"] == "hand_scored"]
    assert scored and scored[0]["score"] == 56
    history = client.get(f"{API}/games/{game['id']}/history").json()
    assert history["commands"] == [{"cmd": "select_blind"}, {"cmd": "play", "cards": [0, 1, 2, 3, 4]}]


def test_errors_are_problem_details(client):
    game = new_game(client)
    gid = game["id"]
    r = client.post(f"{API}/games/{gid}/actions", json={"type": "cash_out"})
    assert r.status_code == 409 and r.json()["code"] == "illegal_action"
    assert r.headers["content-type"] == "application/problem+json"
    act(client, game, type="select_blind")
    r = client.post(f"{API}/games/{gid}/actions", json={"type": "play", "cards": [1], "expected_version": 0})
    assert r.status_code == 409 and r.json()["code"] == "version_conflict" and r.json()["current_version"] == 1
    r = client.post(f"{API}/games/{gid}/actions", json={"type": "teleport"})
    assert r.status_code == 422 and r.json()["code"] == "invalid_request"
    r = client.post(f"{API}/games", json={"seed": "TOO-LONG-SEED"})
    assert r.status_code == 422
    r = client.post(f"{API}/games", json={"seed": "A", "deck": "b_nope"})
    assert r.status_code == 422 and r.json()["code"] == "invalid_settings"
    r = client.get(f"{API}/games/nope")
    assert r.status_code == 404 and r.json()["code"] == "game_not_found"


def test_list_and_delete(client):
    a, b = new_game(client), new_game(client, seed="OTHER")
    listed = client.get(f"{API}/games").json()
    assert [g["id"] for g in listed] == [b["id"], a["id"]]
    assert client.delete(f"{API}/games/{a['id']}").status_code == 204
    assert client.get(f"{API}/games/{a['id']}").status_code == 404


def test_debug_commands(client):
    game = new_game(client)
    r = client.post(f"{API}/games/{game['id']}/debug", json={"command": {"cmd": "add_joker", "key": "j_blueprint"}})
    assert r.status_code == 200 and r.json()["game"]["jokers"][0]["key"] == "j_blueprint"
    r = client.post(f"{API}/games/{game['id']}/debug", json={"command": {"cmd": "add_joker", "key": "j_nope"}})
    assert r.status_code == 409
    off = TestClient(create_app(build_use_cases(Settings(database="memory"))))
    g = off.post(f"{API}/games", json={"seed": "A"}).json()
    r = off.post(f"{API}/games/{g['id']}/debug", json={"command": {"cmd": "cheat", "dollars": 99}})
    assert r.status_code == 403 and r.json()["code"] == "debug_disabled"


def test_runs_survive_a_server_restart(tmp_path):
    settings = Settings(database=str(tmp_path / "runs.db"))
    first = TestClient(create_app(build_use_cases(settings)))
    game = first.post(f"{API}/games", json={"seed": "RESTART1", "deck": "b_yellow", "stake": 4}).json()
    rnd = random.Random(1)
    for _ in range(40):
        if game["phase"] == "game_over":
            break
        a = concrete(game, rnd.choice(game["actions"]), rnd)
        if a is None:
            continue
        r = first.post(f"{API}/games/{game['id']}/actions", json=a)
        if r.status_code == 200:
            game = r.json()["game"]
    second = TestClient(create_app(build_use_cases(settings)))
    assert second.get(f"{API}/games/{game['id']}").json() == game


def test_cors_and_openapi(client):
    r = client.options(f"{API}/games", headers={"Origin": "http://localhost:5173",
                                                 "Access-Control-Request-Method": "POST"})
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] in ("*", "http://localhost:5173")
    schema = client.get("/openapi.json").json()
    assert "/api/v1/games/{game_id}/actions" in schema["paths"]
    assert "GameView" in schema["components"]["schemas"]
