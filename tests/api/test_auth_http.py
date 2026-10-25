"""The API with sign-in: an access token is required and runs are private."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from balatro_api.bootstrap import build_use_cases
from balatro_api.config import Settings
from balatro_api.infrastructure.auth import JwtAuthenticator
from balatro_api.presentation.http import create_app
from tests.tokens import AUDIENCE, ISSUER, FixedKeys, token

API = "/api/v1"
ALICE = {"Authorization": f"Bearer {token(sub='alice', name='Alice')}"}
BOB = {"Authorization": f"Bearer {token(sub='bob', name='Bob')}"}


@pytest.fixture
def client() -> TestClient:
    settings = Settings(database="memory", debug_commands=True)
    auth = JwtAuthenticator(FixedKeys(), ISSUER, AUDIENCE)
    return TestClient(create_app(build_use_cases(settings, authenticator=auth)))


def test_health_and_catalog_are_public(client: TestClient) -> None:
    assert client.get(f"{API}/health").json()["auth"] == "required"
    assert client.get(f"{API}/catalog").status_code == 200


def test_games_need_a_token(client: TestClient) -> None:
    r = client.get(f"{API}/games")
    assert r.status_code == 401
    assert r.json()["code"] == "unauthenticated"
    assert r.headers["www-authenticate"].startswith("Bearer")
    r = client.post(f"{API}/games", json={"seed": "TESTSEED"}, headers={"Authorization": "Bearer junk"})
    assert r.status_code == 401


def test_runs_are_private(client: TestClient) -> None:
    game = client.post(f"{API}/games", json={"seed": "TESTSEED"}, headers=ALICE).json()
    path = f"{API}/games/{game['id']}"

    assert [g["id"] for g in client.get(f"{API}/games", headers=ALICE).json()] == [game["id"]]
    assert client.get(f"{API}/games", headers=BOB).json() == []
    for method, url, body in [("GET", path, None), ("GET", f"{path}/actions", None), ("GET", f"{path}/history", None),
                              ("POST", f"{path}/actions", {"type": "select_blind"}),
                              ("POST", f"{path}/preview", {"cards": []}), ("DELETE", path, None)]:
        r = client.request(method, url, json=body, headers=BOB)
        assert r.status_code == 404, (method, url)
        assert r.json()["code"] == "game_not_found"

    r = client.post(f"{path}/actions", json={"type": "select_blind", "expected_version": 0}, headers=ALICE)
    assert r.status_code == 200
    assert client.delete(path, headers=ALICE).status_code == 204


def test_leaderboards_show_names_not_ids(client: TestClient) -> None:
    for who in (ALICE, BOB):
        game = client.post(f"{API}/games", json={}, headers=who).json()
        game = client.post(f"{API}/games/{game['id']}/actions", json={"type": "select_blind"}, headers=who).json()
        ids = [c["id"] for c in game["game"]["hand"][:5]]
        r = client.post(f"{API}/games/{game['game']['id']}/actions", json={"type": "play", "cards": ids}, headers=who)
        assert r.status_code == 200
    assert client.get(f"{API}/leaderboards/best_hand").status_code == 401
    board = client.get(f"{API}/leaderboards/best_hand", headers=BOB).json()
    assert {e["player"] for e in board["entries"]} == {"Alice", "Bob"}
    assert [e["player"] for e in board["entries"] if e["you"]] == ["Bob"] and board["you"]["player"] == "Bob"
    assert "alice" not in str(board) and "bob" not in str(board)
    mine = client.get(f"{API}/stats/me", headers=ALICE).json()
    assert mine["runs"]["total"] == 1 and mine["career"]["hands_played"] == 1
    assert client.get(f"{API}/stats/global", headers=ALICE).json()["players"] == 2


def test_roles_allow_debug_commands_and_imports(client: TestClient) -> None:
    """The client fixture runs with debug commands on: a server without them."""
    settings = Settings(database="memory")
    auth = JwtAuthenticator(FixedKeys(), ISSUER, AUDIENCE)
    strict = TestClient(create_app(build_use_cases(settings, authenticator=auth)))
    tester = {"Authorization": f"Bearer {token(sub='tess', roles=['tester'])}"}
    dev = {"Authorization": f"Bearer {token(sub='dev', roles=['developer'])}"}
    for who, debug, can_import in ((ALICE, 403, 403), (tester, 200, 403), (dev, 200, 201)):
        game = strict.post(f"{API}/games", json={}, headers=who).json()
        r = strict.post(f"{API}/games/{game['id']}/debug", json={"command": {"cmd": "cheat", "dollars": 50}},
                        headers=who)
        assert r.status_code == debug, (who, r.text)
        body = {"settings": {"seed": "TESTSEED"}, "commands": [{"cmd": "select_blind"}]}
        assert strict.post(f"{API}/games/import", json=body, headers=who).status_code == can_import
    unknown = {"Authorization": f"Bearer {token(sub='x', roles=['emperor', 7])}"}
    game = strict.post(f"{API}/games", json={}, headers=unknown).json()
    assert strict.post(f"{API}/games/{game['id']}/debug", json={"command": {"cmd": "cheat", "dollars": 1}},
                       headers=unknown).status_code == 403
