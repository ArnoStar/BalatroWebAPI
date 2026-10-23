"""Errors of the domain.  Each has a stable ``code`` that clients can rely on."""

from __future__ import annotations


class DomainError(Exception):
    code = "domain_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InvalidGameSettings(DomainError):
    """The settings don't describe a run the game can start."""

    code = "invalid_settings"


class GameNotFound(DomainError):
    code = "game_not_found"

    def __init__(self, game_id: str) -> None:
        super().__init__(f"no game {game_id!r}")
        self.game_id = game_id


class IllegalAction(DomainError):
    """The game doesn't allow this action now (the run is unchanged)."""

    code = "illegal_action"


class GameOver(IllegalAction):
    code = "game_over"

    def __init__(self) -> None:
        super().__init__("the run is over")


class VersionConflict(DomainError):
    """The client acted on a version of the run that is not the current one."""

    code = "version_conflict"

    def __init__(self, expected: int, actual: int) -> None:
        super().__init__(f"the game is at version {actual}, not {expected}")
        self.expected = expected
        self.actual = actual
