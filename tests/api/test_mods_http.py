"""Content mods over HTTP: the registry, runs played with mods, creative mode."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from balatro.mods import examples
from fastapi.testclient import TestClient

from balatro_api.bootstrap import build_use_cases
from balatro_api.config import Settings
from balatro_api.domain import package_hash
from balatro_api.infrastructure.auth import JwtAuthenticator
from balatro_api.presentation.http import create_app
from tests.tokens import AUDIENCE, ISSUER, FixedKeys, token

API = "/api/v1"
ALICE = {"Authorization": f"Bearer {token(sub='alice', name='Alice')}"}
BOB = {"Authorization": f"Bearer {token(sub='bob', name='Bob')}"}
ADMIN = {"Authorization": f"Bearer {token(sub='root', name='Root', roles=['admin'])}"}

TINY: dict[str, Any] = {
    "format": 1, "id": "tiny_jokers", "name": "Tiny Jokers", "version": "1.0.0", "description": "One joker.",
    "tags": ["jokers"],
    "jokers": [{"key": "pair_fan", "name": "Pair Fan", "rarity": 1, "cost": 4, "config": {"mult": 10},
                "text": ["{C:mult}+#1#{} Mult if the hand", "contains a {C:attention}Pair{}"],
                "vars": ["self.mult"],
                "effects": [{"on": "score", "if": "has_hand('Pair')", "do": [{"mult": "self.mult"}]}]}],
}


@pytest.fixture
def client() -> TestClient:
    settings = Settings(database="memory")
    auth = JwtAuthenticator(FixedKeys(), ISSUER, AUDIENCE)
    return TestClient(create_app(build_use_cases(settings, authenticator=auth)))


def version(pkg: dict[str, Any], v: str) -> dict[str, Any]:
    out = copy.deepcopy(pkg)
    out["version"] = v
    return out


def test_the_official_mods_are_in_the_registry(client: TestClient) -> None:
    r = client.get(f"{API}/mods", headers=ALICE)
    assert r.status_code == 200
    ids = {m["id"] for m in r.json()["items"]}
    assert ids == set(examples())
    fruit = client.get(f"{API}/mods/fruit_stand", headers=ALICE).json()
    assert fruit["official"] and fruit["author"] == "Balatro" and fruit["summary"]["jokers"] == 6
    assert fruit["loc"]["ru"]["name"] == "Фруктовая лавка" and fruit["versions"][0]["version"] == "1.0.0"
    package = client.get(f"{API}/mods/fruit_stand/package", headers=ALICE).json()
    assert package == examples()["fruit_stand"] and package_hash(package) == fruit["hash"]
    by_hash = client.get(f"{API}/mods/packages/{fruit['hash']}", headers=ALICE)
    assert by_hash.json() == package and "immutable" in by_hash.headers["cache-control"]
    assert client.get(f"{API}/mods?q=sandbox", headers=ALICE).json()["items"][0]["id"] == "creative"
    assert [m["id"] for m in client.get(f"{API}/mods?tag=decks", headers=ALICE).json()["items"]] == ["wild_rules"]


def test_validate_explains_what_is_wrong(client: TestClient) -> None:
    bad = copy.deepcopy(TINY)
    bad["jokers"][0]["effects"][0]["if"] = "has_hnd('Pair')"
    r = client.post(f"{API}/mods/validate", json=bad, headers=ALICE).json()
    assert not r["valid"] and r["errors"] == ["jokers[0].effects[0].if: unknown function 'has_hnd'"]
    good = client.post(f"{API}/mods/validate", json=TINY, headers=ALICE).json()
    assert good["valid"] and good["hash"] == package_hash(TINY) and good["summary"]["jokers"] == 1
    r = client.post(f"{API}/mods", json=bad, headers=ALICE)
    assert r.status_code == 422 and r.json()["code"] == "invalid_mod" and r.json()["errors"]


def test_publishing_is_the_publishers(client: TestClient) -> None:
    r = client.post(f"{API}/mods", json=TINY, headers=ALICE)
    assert r.status_code == 201 and r.json()["yours"] and r.json()["author"] == "Alice"
    assert client.post(f"{API}/mods", json=TINY, headers=ALICE).json()["code"] == "mod_version_exists"
    assert client.post(f"{API}/mods", json=version(TINY, "1.0.1"), headers=BOB).json()["code"] == "mod_id_taken"
    assert client.post(f"{API}/mods", json=version(examples()["creative"], "9.0.0"),
                       headers=ALICE).json()["code"] == "mod_id_taken"
    r = client.post(f"{API}/mods", json=version(TINY, "1.1.0"), headers=ALICE)
    assert r.status_code == 201 and [v["version"] for v in r.json()["versions"]] == ["1.1.0", "1.0.0"]
    assert client.get(f"{API}/mods/tiny_jokers/package?version=1.0.0", headers=BOB).json()["version"] == "1.0.0"
    # installs: once per player
    for who in (ALICE, BOB, BOB):
        installs = client.post(f"{API}/mods/tiny_jokers/install", headers=who).json()["installs"]
    assert installs == 2
    # unlisting: only its publisher (another player gets "not found"); the package stays
    assert client.delete(f"{API}/mods/tiny_jokers", headers=BOB).status_code == 404
    assert client.delete(f"{API}/mods/tiny_jokers", headers=ALICE).status_code == 204
    assert client.get(f"{API}/mods/tiny_jokers", headers=BOB).status_code == 404
    assert "tiny_jokers" not in {m["id"] for m in client.get(f"{API}/mods", headers=BOB).json()["items"]}
    assert [m["id"] for m in client.get(f"{API}/mods?mine=true", headers=ALICE).json()["items"]] == ["tiny_jokers"]
    assert client.get(f"{API}/mods/packages/{package_hash(TINY)}", headers=BOB).status_code == 200
    assert client.delete(f"{API}/mods/creative", headers=ALICE).status_code == 403
    # a moderator can publish anyone's next version
    assert client.post(f"{API}/mods", json=version(TINY, "2.0.0"), headers=ADMIN).status_code == 201


def new_game(client: TestClient, who: dict[str, str], **body: Any) -> dict[str, Any]:
    r = client.post(f"{API}/games", json={"seed": "MODTEST", **body}, headers=who)
    assert r.status_code == 201, r.json()
    game: dict[str, Any] = r.json()
    return game


def creative(client: TestClient, game: dict[str, Any], who: dict[str, str], **body: Any) -> dict[str, Any]:
    r = client.post(f"{API}/games/{game['id']}/creative", json=body, headers=who)
    assert r.status_code == 200, r.json()
    result: dict[str, Any] = r.json()
    return result


def test_a_run_with_mods(client: TestClient) -> None:
    game = new_game(client, ALICE, mods=[{"id": "fruit_stand"}, {"id": "wild_rules"}, {"package": TINY}])
    mods = game["settings"]["mods"]
    assert [m["id"] for m in mods] == ["fruit_stand", "wild_rules", "tiny_jokers"]
    assert mods[2]["hash"] == package_hash(TINY) and not any(m["creative"] for m in mods)
    assert not any(a["type"] == "creative" for a in game["actions"])
    # (no creative mod: no creative changes)
    r = client.post(f"{API}/games/{game['id']}/creative", json={"op": "win"}, headers=ALICE)
    assert r.status_code == 409
    # the inline package is kept: the run's history has the packages' logic
    assert client.get(f"{API}/mods/packages/{package_hash(TINY)}", headers=ALICE).json() == TINY
    history = client.get(f"{API}/games/{game['id']}/history", headers=ALICE).json()
    assert set(history["mod_packages"]) == {m["hash"] for m in mods}
    assert "assets" not in history["mod_packages"][mods[0]["hash"]]
    # the run doesn't count
    runs = client.get(f"{API}/games", headers=ALICE).json()
    assert [r["counted"] for r in runs] == [False]


def test_a_mods_deck_and_an_invalid_mod(client: TestClient) -> None:
    game = new_game(client, ALICE, deck="b_wild_rules_gardener", stake=8, mods=[{"id": "wild_rules"}])
    assert game["dollars"] == 14 and game["settings"]["stake"] == 8
    r = client.post(f"{API}/games", json={"deck": "b_wild_rules_gardener"}, headers=ALICE)
    assert r.status_code == 422  # (without the mod, there is no such deck)
    bad = copy.deepcopy(TINY)
    bad["jokers"][0]["effects"][0]["do"] = [{"chips": "self.nope"}]
    r = client.post(f"{API}/games", json={"mods": [{"package": bad}]}, headers=ALICE)
    assert r.status_code == 422 and r.json()["code"] == "invalid_mod"
    assert r.json()["errors"] == ["jokers[0].effects[0].do[0].chips: 'self' has no field 'nope' (it has mult)"]
    assert client.post(f"{API}/games", json={"mods": [{"id": "nowhere"}]}, headers=ALICE).status_code == 404


def test_creative_mode(client: TestClient) -> None:
    game = new_game(client, ALICE, mods=[{"id": "creative"}, {"id": "fruit_stand"}])
    assert game["settings"]["mods"][0]["creative"]
    assert any(a["type"] == "creative" for a in game["actions"])
    g = creative(client, game, ALICE, op="set", what="money", value=50)["game"]
    assert g["dollars"] == 50
    g = creative(client, game, ALICE, op="add", key="j_fruit_stand_cherry_seven", edition="foil")["game"]
    assert [(j["key"], j["edition"]) for j in g["jokers"]] == [("j_fruit_stand_cherry_seven", "foil")]
    joker = g["jokers"][0]["id"]
    g = creative(client, game, ALICE, op="edit", card=joker, edition="none", eternal=True)["game"]
    assert g["jokers"][0]["edition"] is None and g["jokers"][0]["stickers"]["eternal"]
    client.post(f"{API}/games/{game['id']}/actions", json={"type": "select_blind"}, headers=ALICE)
    result = creative(client, game, ALICE, op="add_card", rank="7", suit="Hearts", to="hand")
    assert any(c["rank"] == "7" and c["suit"] == "Hearts" for c in result["game"]["hand"])
    r = client.post(f"{API}/games/{game['id']}/creative", json={"op": "edit", "card": 99999}, headers=ALICE)
    assert r.status_code == 409
    # someone else's run: not found
    r = client.post(f"{API}/games/{game['id']}/creative", json={"op": "win"}, headers=BOB)
    assert r.status_code == 404
    g = creative(client, game, ALICE, op="win")["game"]
    assert g["phase"] == "round_eval"
    # the history replays it all: the watch copy gets the creative steps, cards by id
    watch = client.post(f"{API}/games/{game['id']}/watch", headers=ALICE).json()
    creative_steps = [s["action"] for s in watch["steps"] if s["action"]["type"] == "creative"]
    assert creative_steps[2] == {"type": "creative", "op": "edit", "edition": "none", "eternal": True, "card": joker}
    assert watch["game"]["settings"]["mods"] == game["settings"]["mods"]


def test_a_modded_run_replays_on_another_server(client: TestClient) -> None:
    game = new_game(client, ALICE, mods=[{"id": "creative"}, {"package": TINY}])
    creative(client, game, ALICE, op="add", key="j_tiny_jokers_pair_fan")
    client.post(f"{API}/games/{game['id']}/actions", json={"type": "select_blind"}, headers=ALICE)
    history = client.get(f"{API}/games/{game['id']}/history", headers=ALICE).json()
    other = TestClient(create_app(build_use_cases(Settings(database="memory", debug_commands=True),
                                                  official_mods=False)))
    body = {"settings": history["settings"], "commands": history["commands"],
            "start_profile": history["start_profile"], "mod_packages": history["mod_packages"]}
    r = other.post(f"{API}/games/import", json=body)
    assert r.status_code == 201, r.json()
    mine = client.get(f"{API}/games/{game['id']}", headers=ALICE).json()
    assert r.json()["jokers"] == mine["jokers"] and r.json()["hand"] == mine["hand"]
    # without the packages, the other server can't rebuild it
    third = TestClient(create_app(build_use_cases(Settings(database="memory", debug_commands=True),
                                                  official_mods=False)))
    r = third.post(f"{API}/games/import", json={k: v for k, v in body.items() if k != "mod_packages"})
    assert r.status_code == 422
