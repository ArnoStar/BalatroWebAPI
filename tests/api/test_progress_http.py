"""The player's progress (a new account starts like a new save), the testers' "unlock everything",
public profiles, and watching runs again."""

from __future__ import annotations

from typing import Any

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
TESTER = {"Authorization": f"Bearer {token(sub='tess', name='Tess', roles=['tester'])}"}
DEV = {"Authorization": f"Bearer {token(sub='dev', name='Dev', roles=['developer'])}"}


@pytest.fixture
def client() -> TestClient:
    settings = Settings(database="memory", debug_commands=False)
    auth = JwtAuthenticator(FixedKeys(), ISSUER, AUDIENCE)
    return TestClient(create_app(build_use_cases(settings, authenticator=auth)))


def lose(client: TestClient, who: dict[str, str], seed: str = "WATCHME1") -> dict[str, Any]:
    """A run lost at once: four one-card hands don't beat the Small Blind."""
    game = client.post(f"{API}/games", json={"seed": seed}, headers=who).json()
    game = client.post(f"{API}/games/{game['id']}/actions", json={"type": "select_blind"}, headers=who).json()["game"]
    while game["phase"] == "playing":
        r = client.post(f"{API}/games/{game['id']}/actions", json={"type": "play", "cards": [game["hand"][0]["id"]]},
                        headers=who)
        game = r.json()["game"]
    assert game["phase"] == "game_over"
    return game


def test_a_new_account_starts_like_a_new_save(client: TestClient) -> None:
    me = client.get(f"{API}/players/me", headers=ALICE).json()
    p = me["progress"]
    assert p["challenges_unlocked"] == 0 and p["max_stakes"]["b_red"] == 1 and not p["all_unlocked"]
    assert "j_throwback" not in p["unlocked"] and not p["can_unlock_all"]
    for body in ({"deck": "b_plasma"}, {"deck": "b_red", "stake": 2}, {"challenge": "c_omelette_1"}):
        r = client.post(f"{API}/games", json=body, headers=ALICE)
        assert r.status_code == 409 and r.json()["code"] == "locked", body
    assert client.post(f"{API}/games", json={"deck": "b_red", "stake": 1}, headers=ALICE).status_code == 201


def test_what_a_run_unlocks_is_kept(client: TestClient) -> None:
    game = client.post(f"{API}/games", json={}, headers=ALICE).json()
    r = client.post(f"{API}/games/{game['id']}/actions", json={"type": "continue"}, headers=ALICE)
    assert r.status_code == 200 and r.json()["game"]["version"] == 1  # it unlocked Throwback: recorded
    assert {"type": "card_unlocked", "key": "j_throwback", "set": "Joker"}.items() <= next(
        e for e in r.json()["events"] if e["type"] == "card_unlocked").items()
    r = client.post(f"{API}/games/{game['id']}/actions", json={"type": "continue"}, headers=ALICE)
    assert r.json()["game"]["version"] == 1  # nothing more to unlock: not recorded
    assert "j_throwback" in client.get(f"{API}/players/me", headers=ALICE).json()["progress"]["unlocked"]
    assert "j_throwback" not in client.get(f"{API}/players/me", headers=BOB).json()["progress"]["unlocked"]
    # a seeded run unlocks nothing
    seeded = client.post(f"{API}/games", json={"seed": "SEEDED11"}, headers=BOB).json()
    r = client.post(f"{API}/games/{seeded['id']}/actions", json={"type": "continue"}, headers=BOB)
    assert r.json()["game"]["version"] == 0


def test_testers_can_unlock_everything(client: TestClient) -> None:
    r = client.patch(f"{API}/players/me", json={"all_unlocked": True}, headers=ALICE)
    assert r.status_code == 403 and r.json()["code"] == "unlock_all_forbidden"
    me = client.patch(f"{API}/players/me", json={"all_unlocked": True}, headers=TESTER).json()
    assert me["progress"]["all_unlocked"] and me["progress"]["can_unlock_all"]
    assert me["progress"]["max_stakes"]["b_plasma"] == 8 and me["progress"]["challenges_unlocked"] > 0
    game = client.post(f"{API}/games", json={"deck": "b_plasma", "stake": 8}, headers=TESTER).json()
    client.post(f"{API}/games/{game['id']}/actions", json={"type": "continue"}, headers=TESTER)
    # switched off: back to the real progress, which the unlocked run didn't change
    me = client.patch(f"{API}/players/me", json={"all_unlocked": False}, headers=TESTER).json()
    assert not me["progress"]["all_unlocked"] and "j_throwback" not in me["progress"]["unlocked"]
    assert client.post(f"{API}/games", json={"deck": "b_plasma"}, headers=TESTER).status_code == 409


def test_finished_runs_can_be_watched_by_anyone(client: TestClient) -> None:
    original = lose(client, ALICE)
    watch = client.post(f"{API}/games/{original['id']}/watch", headers=BOB)
    assert watch.status_code == 201, watch.text
    w = watch.json()
    assert w["source"] == original["id"] and w["owner_name"] == "Alice" and len(w["steps"]) == original["version"]
    copy = w["game"]
    assert copy["id"] != original["id"] and copy["version"] == 0
    for step in w["steps"]:
        r = client.post(f"{API}/games/{copy['id']}/actions", json=step["action"], headers=BOB)
        assert r.status_code == 200, (step, r.text)
        copy = r.json()["game"]
    for key in ("phase", "ante", "round", "dollars", "round_score", "hand", "jokers"):
        assert copy[key] == original[key], key
    # the copy isn't one of Bob's runs, and adds nothing to his progress or stats
    assert client.get(f"{API}/games", headers=BOB).json() == []
    assert client.get(f"{API}/history", headers=BOB).status_code == 404
    assert client.get(f"{API}/games/{original['id']}/history", headers=BOB).json()["start_profile"] is not None


def test_unfinished_and_private_runs_cant_be_watched(client: TestClient) -> None:
    live = client.post(f"{API}/games", json={}, headers=ALICE).json()
    for path in (f"{API}/games/{live['id']}/watch", f"{API}/games/{live['id']}/history"):
        r = client.request("POST" if path.endswith("watch") else "GET", path, headers=BOB)
        assert r.status_code == 404 and r.json()["code"] == "game_not_found"
    assert client.post(f"{API}/games/{live['id']}/watch", headers=ALICE).status_code == 201  # one's own
    assert client.post(f"{API}/games/{live['id']}/watch", headers=DEV).status_code == 201  # developers: any
    done = lose(client, ALICE, "PRIVATE1")
    client.patch(f"{API}/players/me", json={"private": True}, headers=ALICE)
    assert client.post(f"{API}/games/{done['id']}/watch", headers=BOB).status_code == 404


def test_profiles(client: TestClient) -> None:
    done = lose(client, ALICE)
    client.post(f"{API}/games", json={}, headers=ALICE)  # unfinished: only Alice sees it on her profile
    seen = client.get(f"{API}/players/alice", headers=BOB).json()
    assert seen["name"] == "Alice" and not seen["you"] and not seen["private"]
    assert [r["id"] for r in seen["runs"]] == [done["id"]]
    assert seen["collection"]["jokers"]["total"] == 150 and seen["collection"]["decks"]["found"] >= 1
    assert seen["stats"] is not None
    assert len(client.get(f"{API}/players/alice", headers=ALICE).json()["runs"]) == 2
    client.patch(f"{API}/players/me", json={"private": True}, headers=ALICE)
    hidden = client.get(f"{API}/players/alice", headers=BOB).json()
    assert hidden["private"] and hidden["name"] == "Alice" and hidden["runs"] == [] and hidden["stats"] is None
    assert client.get(f"{API}/players/alice", headers=DEV).json()["stats"] is not None
    r = client.get(f"{API}/players/nobody", headers=BOB)
    assert r.status_code == 404 and r.json()["code"] == "player_not_found"
