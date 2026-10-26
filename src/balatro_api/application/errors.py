"""Errors of the application layer (as opposed to the game's rules)."""

from __future__ import annotations

from balatro_api.domain import DomainError


class NotAuthenticated(DomainError):
    """No access token, or one the identity service didn't sign (or expired)."""

    code = "unauthenticated"


class AuthUnavailable(DomainError):
    """The identity service's keys couldn't be fetched to check a token."""

    code = "auth_unavailable"


class DebugCommandsDisabled(DomainError):
    code = "debug_disabled"

    def __init__(self) -> None:
        super().__init__("debug commands are off on this server (the tester role allows them)")


class ImportForbidden(DomainError):
    code = "import_forbidden"

    def __init__(self) -> None:
        super().__init__("rebuilding a run needs the developer role (or BALATRO_API_ADMINS, or debug commands)")


class PlayerNotFound(DomainError):
    code = "player_not_found"

    def __init__(self, player_id: str) -> None:
        super().__init__(f"no player {player_id!r}")


class UnlockAllForbidden(DomainError):
    code = "unlock_all_forbidden"

    def __init__(self) -> None:
        super().__init__("unlocking everything needs the tester, developer or admin role")
