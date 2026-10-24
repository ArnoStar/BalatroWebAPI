# BalatroWebAPI: `make` lists the commands.
#
# Alone:            make install && make run         (http://127.0.0.1:8000, docs at /docs)
# With sign-in:     make run-auth                    (the identity service on :8001: its `make run`)
# Everything:       make dev in ../BalatroFrontEnd   (the whole site, each part from its repository)
.DEFAULT_GOAL := help
.PHONY: help install run run-auth check test lint typecheck docker

STACK := ../BalatroFrontEnd/docker-compose.yml
PORT ?= 8000
# the identity service run locally: the tokens' issuer (its PUBLIC_URL) and where its keys are
IDENTITY_URL ?= http://localhost:8001
IDENTITY_JWKS ?= http://127.0.0.1:8001/.well-known/jwks.json

help:
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-10s %s\n", $$1, $$2}'

install: ## dependencies (the engine comes from its git tag)
	uv sync

run: ## serve on :8000 without sign-in (everyone is one player), reloading on changes
	BALATRO_API_DEBUG_COMMANDS=1 uv run uvicorn balatro_api.main:app --reload --port $(PORT)

run-auth: ## the same, with sign-in: tokens of the identity service at IDENTITY_URL
	BALATRO_API_DEBUG_COMMANDS=1 \
	BALATRO_API_AUTH_JWKS_URL=$(IDENTITY_JWKS) \
	BALATRO_API_AUTH_ISSUER=$(IDENTITY_URL) \
	uv run uvicorn balatro_api.main:app --reload --port $(PORT)

check: test lint typecheck ## everything CI runs (tests, ruff, mypy)

test: ## the tests (about 5 s)
	uv run pytest

lint: ## ruff
	uv run ruff check src tests

typecheck: ## mypy --strict
	uv run mypy

docker: ## this service in Docker, from the game's compose file (http://127.0.0.1:8000)
	docker compose -f $(STACK) up -d --build api
