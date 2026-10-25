from __future__ import annotations

from balatro_api.application.dto import Player
from balatro_api.application.permissions import Permission, allowed


def test_roles_allow():
    assert not allowed(Player(id="p"), Permission.DEBUG_COMMANDS)
    assert allowed(Player(id="p", roles=frozenset({"tester"})), Permission.DEBUG_COMMANDS)
    assert not allowed(Player(id="p", roles=frozenset({"tester"})), Permission.IMPORT_RUNS)
    assert allowed(Player(id="p", roles=frozenset({"developer"})), Permission.IMPORT_RUNS)
    assert all(allowed(Player(id="p", roles=frozenset({"admin"})), p) for p in Permission)
    assert not allowed(Player(id="p", roles=frozenset({"unknown"})), Permission.DEBUG_COMMANDS)
