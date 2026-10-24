"""Server settings, from environment variables."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database: str = "balatro.db"  # a SQLite file, or "memory" (runs are lost when the server stops)
    cors_origins: tuple[str, ...] = ("*",)
    cache_size: int = 256  # runs whose game is kept in memory (others are replayed when needed)
    debug_commands: bool = False  # POST /games/{id}/debug (money, jokers, bosses ... for front-end testing)
    # sign-in with the identity service (BalatroIndentityService): on when the
    # JWKS URL is set; then the issuer (its PUBLIC_URL) is required too
    auth_jwks_url: str | None = None
    auth_issuer: str | None = None
    auth_audience: str = "balatro"

    def __post_init__(self) -> None:
        if self.auth_jwks_url and not self.auth_issuer:
            raise ValueError("BALATRO_API_AUTH_ISSUER is required with BALATRO_API_AUTH_JWKS_URL")

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> Settings:
        d = cls()
        origins = env.get("BALATRO_API_CORS_ORIGINS")
        return cls(
            database=env.get("BALATRO_API_DATABASE", d.database),
            cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()) if origins else d.cors_origins,
            cache_size=int(env.get("BALATRO_API_CACHE_SIZE", d.cache_size)),
            debug_commands=env.get("BALATRO_API_DEBUG_COMMANDS", "").lower() in ("1", "true", "yes", "on"),
            auth_jwks_url=env.get("BALATRO_API_AUTH_JWKS_URL") or None,
            auth_issuer=(env.get("BALATRO_API_AUTH_ISSUER") or "").rstrip("/") or None,
            auth_audience=env.get("BALATRO_API_AUTH_AUDIENCE") or d.auth_audience,
        )
