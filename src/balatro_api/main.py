"""``uvicorn balatro_api.main:app`` (or the ``balatro-api`` command).
Settings come from BALATRO_API_* environment variables (see config.py)."""

from __future__ import annotations

import logging
import os

from .bootstrap import build_use_cases
from .config import Settings
from .presentation.http import create_app

# the server's own log lines (one per request, with its id; errors), next to uvicorn's
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
settings = Settings.from_env()
app = create_app(build_use_cases(settings), settings.cors_origins)


def run() -> None:
    import uvicorn

    uvicorn.run("balatro_api.main:app", host=os.environ.get("BALATRO_API_HOST", "127.0.0.1"),
                port=int(os.environ.get("BALATRO_API_PORT", "8000")), access_log=False)  # (requests.py logs them)
