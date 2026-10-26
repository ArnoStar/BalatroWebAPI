"""What the identity service's roles allow in this API.

The identity service gives accounts roles (``roles`` in the access token);
each service decides what a role allows there. A role this API doesn't know
allows nothing.
"""

from __future__ import annotations

from enum import StrEnum

from .dto import Player


class Permission(StrEnum):
    DEBUG_COMMANDS = "runs:debug"  # POST /games/{id}/debug on one's own runs (they then don't count)
    IMPORT_RUNS = "runs:import"  # POST /games/import: rebuild a run from a history (bug reports)
    UNLOCK_ALL = "progress:unlock_all"  # PATCH /players/me {all_unlocked}: new runs fully unlocked (tests)
    WATCH_ALL = "runs:watch_all"  # watch anyone's runs, also unfinished ones and private players'


ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "admin": frozenset(Permission),
    "developer": frozenset({Permission.DEBUG_COMMANDS, Permission.IMPORT_RUNS, Permission.UNLOCK_ALL,
                            Permission.WATCH_ALL}),
    "tester": frozenset({Permission.DEBUG_COMMANDS, Permission.UNLOCK_ALL}),
}


def allowed(player: Player, permission: Permission) -> bool:
    return any(permission in ROLE_PERMISSIONS.get(role, frozenset()) for role in player.roles)
