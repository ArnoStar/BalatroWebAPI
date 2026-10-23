"""Errors of the application layer (as opposed to the game's rules)."""

from __future__ import annotations

from balatro_api.domain import DomainError


class DebugCommandsDisabled(DomainError):
    code = "debug_disabled"

    def __init__(self) -> None:
        super().__init__("debug commands are disabled on this server")
