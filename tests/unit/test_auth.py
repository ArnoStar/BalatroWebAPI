"""Checking the identity service's access tokens."""

from __future__ import annotations

from datetime import timedelta

import pytest

from balatro_api.application.dto import Player
from balatro_api.application.errors import NotAuthenticated
from balatro_api.config import Settings
from balatro_api.domain import ANONYMOUS_PLAYER
from balatro_api.infrastructure.auth import AnonymousAuthenticator, JwtAuthenticator
from tests.tokens import AUDIENCE, ISSUER, OTHER_KEY, FixedKeys, token


@pytest.fixture
def auth() -> JwtAuthenticator:
    return JwtAuthenticator(FixedKeys(), ISSUER, AUDIENCE)


def test_a_valid_token(auth: JwtAuthenticator) -> None:
    assert auth.authenticate(token()) == Player(id="player-1", name="Jimbo")
    assert auth.authenticate(token(name=None)) == Player(id="player-1", name=None)


@pytest.mark.parametrize("bad", [
    None,
    "",
    "not a jwt",
    token(key=OTHER_KEY),  # not signed by the identity service
    token(lifetime=timedelta(minutes=-5)),  # expired (beyond the leeway)
    token(iss="http://elsewhere"),
    token(aud="another-service"),
    token(typ="refresh"),
])
def test_refused_tokens(auth: JwtAuthenticator, bad: str | None) -> None:
    with pytest.raises(NotAuthenticated):
        auth.authenticate(bad)


def test_a_token_without_a_subject(auth: JwtAuthenticator) -> None:
    import jwt

    from tests.tokens import KEY
    no_sub = jwt.encode({"iss": ISSUER, "aud": AUDIENCE, "exp": 2_000_000_000, "iat": 0, "typ": "access"}, KEY,
                        algorithm="RS256")
    with pytest.raises(NotAuthenticated):
        auth.authenticate(no_sub)


def test_anonymous() -> None:
    anonymous = AnonymousAuthenticator()
    assert not anonymous.required
    assert anonymous.authenticate(None) == anonymous.authenticate("anything") == Player(id=ANONYMOUS_PLAYER)


def test_settings() -> None:
    s = Settings.from_env({"BALATRO_API_AUTH_JWKS_URL": "http://identity:8000/.well-known/jwks.json",
                           "BALATRO_API_AUTH_ISSUER": "https://example.com/identity/"})
    assert s.auth_issuer == "https://example.com/identity" and s.auth_audience == "balatro"
    with pytest.raises(ValueError, match="ISSUER"):
        Settings.from_env({"BALATRO_API_AUTH_JWKS_URL": "http://identity:8000/.well-known/jwks.json"})
