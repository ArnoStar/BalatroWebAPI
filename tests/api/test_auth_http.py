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
