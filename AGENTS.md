# AGENTS.md

Rules for anyone (human or agent) changing this repository. `README.md`
describes the API; this file says how to work on it.

## What this project is

An HTTP API, used by a front end, to play Balatro runs. All game logic comes
from **BalatroEngine** (`balatroengine`, github.com/ArnoStar/BalatroEngine),
which reproduces the original game exactly.

## Non-negotiable rules

1. **No game rule lives here.** Scoring, legality, prices, shop contents and
   anything random are the engine's. If the API needs a rule the engine
   doesn't expose, add it to the engine (with its tests against the original
   game) and bump the engine version. Do not approximate it here.
2. **The command history is the run.** A run is its `GameSettings` plus the
   ordered engine commands the player made. Everything else is derived by
   replaying them. Never store derived game state as the source of truth
   (`Progress` is only a listing cache).
3. **Same seed and same choices give the same run.** Nothing may consume
   randomness or change timing outside the player's commands. Recording
   feedback, previews, views and legal-action lists must not change the game.
   The engine guarantees this for `start_feedback`, `preview_hand`,
   `legal_actions` and `snapshot`; don't call anything else on a game outside
   an action.
4. **An action that fails changes nothing.** Actions are played on
   `Game.clone()`. The clone replaces the cached game (`commit`) only after the
   run is saved. Keep that order: apply on a copy → record → save
   (optimistic, `expected_version`) → commit.
5. **Only what the player can see.** Views never expose the deck order, RNG
   state, upcoming shop or pack contents, or the identity of face-down cards.
   The deck view has no card ids, because they would let a client track a card
   that is later drawn face down.
6. **A run is its owner's.** Every use case takes the `Player` first and loads
   runs through `owned_run`. Another player's run is `GameNotFound` (404),
   never 403: don't reveal that it exists. Players come from the identity
   service's access tokens (`Authenticator` port). Never trust a player id the
   client sends any other way.
7. **A cached game is touched by one thread at a time.** Inside the engine
   adapter, always go through `BalatroEngine._game(run)`, which holds the
   run's lock. Even read-only engine calls such as `legal_actions` or
   `preview_hand` swap state temporarily.

## Architecture (clean architecture)

```
domain  <-  application  <-  infrastructure, presentation  <-  bootstrap, main
```

- `domain/`: `Run`, `GameSettings`, `Progress`, `Command`, errors with stable
  `code`s. Pure Python, with no imports from other layers.
- `application/`: one class per use case (`use_cases.py`), the DTOs that are
  the API contract (`dto.py`), and the ports it needs (`ports.py`:
  `GameEngine`, `GameRepository`, `Authenticator`, `Clock`, `IdGenerator`).
  No web framework, no engine import.
- `infrastructure/`: adapters for the ports. `engine/` is the **only** place
  that imports `balatro`: `adapter.py` handles the cache, replay and
  transactions, `commands.py` translates card ids to indices and builds legal
  actions, `presenter.py` builds the views, `catalog.py` the static data.
  `persistence/` has SQLite and in-memory storage; `system.py` has the clock
  and ids; `auth.py` checks the identity service's tokens (PyJWT and its
  JWKS client) or makes everyone the anonymous player.
- `presentation/http/`: FastAPI routes, request schemas (pydantic) and the
  mapping of errors to HTTP. It depends on application use cases, never on
  infrastructure.
- `bootstrap.py` is the composition root. `main.py` builds the app from
  environment settings.

`tests/test_architecture.py` enforces these import rules. Fix the code, not
the test.

## Conventions

- **API contract:** the dataclasses in `application/dto.py` are serialized as
  they are, so field names are the JSON names (snake_case). Changes inside
  `/api/v1` must be additive. Never rename or remove a field, and never change
  its meaning. Document new fields in their docstrings, which become the
  OpenAPI schema.
- **Cards** are referred to by `id` (the engine's `sort_id`) in requests and
  responses. Indices exist only in stored engine commands.
- **Errors** are domain/application exceptions with a `code`, mapped to
  problem details in `presentation/http/errors.py`. An illegal move is
  `409 illegal_action`; a stale `expected_version` is `409 version_conflict`.
- **Requests** are pydantic models in `presentation/http/schemas.py`, converted
  to application DTOs with `to_dto()`. Pydantic and FastAPI stay in
  `presentation/`.
- **Style:** ruff (line length 120) and `mypy --strict`. Use absolute imports
  across layers (`from balatro_api.domain import ...`) and relative imports
  within a layer. DTOs are `@dataclass(frozen=True, kw_only=True)`.

## Adding things

- **A new action type:** add it to `ActionType` and `PlayerAction` in
  `dto.py`, to the request union in `schemas.py`, and to `to_command` and
  `legal_actions` in `infrastructure/engine/commands.py`. Add an HTTP test.
- **A new view field:** add it to the DTO, fill it in `presenter.py`, check
  rule 5 (hidden information), and test it.
- **A new endpoint:** add a use case in `application/use_cases.py` that takes
  the `Player` first, add it to `UseCases`, wire it in `bootstrap.py`, and add
  a route with `player: CurrentPlayer`. Add unit tests with fakes and an HTTP
  test, including one where another player is refused
  (`tests/api/test_auth_http.py`; `tests/tokens.py` signs test tokens).
- **A new storage backend:** implement `GameRepository`, including the
  optimistic `save(run, expected_version)`. Run it through
  `tests/integration/test_sqlite.py`'s parametrized tests.

## The engine dependency

`pyproject.toml` pins the engine to a git tag (`[tool.uv.sources]`). To
upgrade it:

1. Tag and push a new engine release.
2. Update the tag and run `uv lock`.
3. Run the whole test suite.

Runs store the `engine_version` they were created with. An engine release that
changes game logic can make old runs replay differently. Say so in the release
notes, and keep old runs replayable if they matter.

To develop against a local engine checkout, run
`uv pip install -e ../BalatroEngine`, then `uv run --no-sync ...`. A plain
`uv sync` goes back to the pinned tag.

## Commands

```
make install                    # uv sync (Python 3.12+)
make test                       # uv run pytest, all tests (about 5 s)
make lint                       # uv run ruff check src tests
make typecheck                  # uv run mypy
make check                      # the three
make run                        # serve on 127.0.0.1:8000 (reload), docs at /docs; make run-auth: with sign-in
```

Before committing, all three checks must pass.
