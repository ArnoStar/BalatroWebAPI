from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from balatro_api.bootstrap import build_use_cases
from balatro_api.config import Settings
from balatro_api.presentation.http import create_app


@pytest.fixture
def client() -> TestClient:
    settings = Settings(database="memory", debug_commands=True)
    return TestClient(create_app(build_use_cases(settings)))
