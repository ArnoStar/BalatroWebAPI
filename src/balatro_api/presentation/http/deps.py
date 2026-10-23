"""FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from balatro_api.application.use_cases import UseCases


def use_cases(request: Request) -> UseCases:
    uc: UseCases = request.app.state.use_cases
    return uc


Uses = Annotated[UseCases, Depends(use_cases)]
