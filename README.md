# BalatroWebAPI

An HTTP API to play Balatro runs, built for a front end. The game logic is
[BalatroEngine](https://github.com/ArnoStar/BalatroEngine)'s, which reproduces
Balatro 1.0.1o exactly: the same seed and the same choices give the same run
as in the original game. This service never reimplements a rule; it stores
runs, translates requests and shows the player what the game would show.

```
make install
make run                                # http://127.0.0.1:8000 (docs at /docs), no sign-in
make run-auth                           # with sign-in: the identity service on :8001
make check                              # tests, ruff, mypy
```

(`uv run balatro-api` still works.) `make` lists every command.
BalatroFrontEnd's `make dev` runs the whole site, this API included.

Full documentation: [`docs/`](docs/README.md) (getting started, every endpoint, every
data model, the front-end flows).

## Players and sign-in

Players sign in with **BalatroIndentityService**, which gives them RS256 access
tokens (JWTs). With `BALATRO_API_AUTH_JWKS_URL` set, every game route needs one
(`Authorization: Bearer <token>`). The API checks the token's signature against
the identity service's public keys (fetched from that URL and cached), its
issuer (`BALATRO_API_AUTH_ISSUER`), its audience and its expiry. It never calls
the identity service per request.

A run belongs to the player who started it (the token's `sub`). Nobody else can
list, read or play it: someone else's run answers 404 `game_not_found`, as if
it didn't exist.

Without `BALATRO_API_AUTH_JWKS_URL`, the server runs without sign-in. Every
caller is the same anonymous player, `local`, which owns the runs made before
runs had owners. This mode is for development and for the front end's
frame-by-frame tools. `GET /health` says which mode is on: `"auth": "required"`
or `"off"`.

## Playing a run

```
POST /api/v1/games                {"seed": "TESTSEED", "deck": "b_red", "stake": 1}
GET  /api/v1/games/{id}
POST /api/v1/games/{id}/actions   {"type": "select_blind", "expected_version": 0}
POST /api/v1/games/{id}/preview   {"cards": [35, 37, 25]}
```

A run waits for one decision at a time. `GET /games/{id}` returns a
`GameView`: everything the player sees on screen, its `phase` (`blind_select`,
`playing`, `round_eval`, `shop`, `pack`, `game_over`) and `actions`, the
actions the game allows right now. Send one to `POST /games/{id}/actions`. The
server plays it, runs the game until it waits for the player again, and
returns the new `GameView` together with `events`.

| Endpoint | |
|---|---|
| `GET /api/v1/health` | Server and engine versions |
| `GET /api/v1/catalog` | Static data: every deck, stake, challenge, joker, consumable, voucher, booster, tag, blind, poker hand and card, with names, prices and sprite positions (ETag cached) |
| `POST /api/v1/games` | Start a run (`seed` optional, `deck`, `stake` 1-8, `challenge`, `game_speed`) |
| `GET /api/v1/games` | Runs, most recently played first (`limit`, `offset`) |
| `GET /api/v1/games/{id}` | The run as the player sees it |
| `DELETE /api/v1/games/{id}` | Delete a run |
| `GET /api/v1/games/{id}/actions` | What can be done now (also in the `GameView`) |
| `POST /api/v1/games/{id}/actions` | Act |
| `POST /api/v1/games/{id}/preview` | The poker hand some selected cards make, as the game shows it while selecting |
| `GET /api/v1/games/{id}/history` | The run's settings and commands (for bug reports and replays) |
| `POST /api/v1/games/{id}/debug` | Test helpers, only with `BALATRO_API_DEBUG_COMMANDS=1` |

The OpenAPI schema is at `/openapi.json`. A TypeScript front end can generate
its types from it, for example with `npx openapi-typescript
http://127.0.0.1:8000/openapi.json -o src/api.d.ts`.

### Actions

Cards are referred to by `id`. A card keeps its id for the whole run, so a
front end can follow it from the deck to the hand, the play area and the
discard pile.

| `type` | Fields | When |
|---|---|---|
| `select_blind`, `skip_blind`, `reroll_boss` | | blind select |
| `play`, `discard` | `cards`: 1 to 5 hand card ids | playing |
| `sort` | `mode`: `rank` or `suit` | playing |
| `cash_out` | | round evaluation |
| `buy` | `card`; `use: true` buys a consumable and uses it at once | shop (cards, the voucher, booster packs) |
| `reroll`, `end_shop` | | shop |
| `pick` | `card`, `targets` (hand card ids, for Tarot and Spectral cards) | booster pack |
| `skip_pack` | | booster pack |
| `use` | `card`, `targets` | most of the time |
| `sell` | `card` | most of the time |
| `move` | `card`, `to` (new position, 0 = leftmost) | reorder jokers, consumables or the hand |

`actions` lists each possible action with what it leaves open, such as
`min_cards`/`max_cards` for `play`, `min_targets`/`max_targets` for a
consumable, or `cost` for a purchase.

Every action may carry `expected_version`, the `version` of the `GameView` it
was chosen from. If the run has changed since then (a double click, a second
tab), the server refuses the action with `409 version_conflict` instead of
applying it to another state.

### Events: what the player saw happen

An action's response lists, in order, what the game shows while it runs. `t`
is the time in seconds at which the game shows it (at the run's game speed,
60 fps), so a front end can replay the animation at the game's own pace:

| `type` | |
|---|---|
| `card_moved` | a card arrives in an area (`to`: `hand`, `play`, `discard`, `jokers` ...) |
| `card_flipped`, `card_removed` | a card turns over (face up: with its `view`), a card leaves the game |
| `card_juiced` | the joker behind a scored or held card's effect wiggles (`card`) |
| `hand` | the scoring panel: `hand`, `level`, `chips`, `mult`, `hand_score` (only what changes) |
| `card_text` | a pop-up over a card: `effect` (`chips`, `mult`, `x_mult`, `dollars`, `again`, `debuffed`, `message` ...) and `amount` |
| `hand_scored` | the hand's chips, mult and score, and the round score after it |
| `round_score`, `dollars`, `status_text` | the round score is reset (at cash out), money changes, text over the play area |

### What the player can't see

A view holds only what the game shows: never the deck's order, the RNG state or
what a face-down card is. Face-down cards (The House, The Wheel, Amber Acorn)
come with their id only. The deck's remaining cards are listed sorted and
without ids, as in the game's deck view.

### Errors

Errors are [problem details](https://www.rfc-editor.org/rfc/rfc9457)
(`application/problem+json`) with a stable `code`:

| Status | `code` | |
|---|---|---|
| 401 | `unauthenticated` | no access token, or one that is invalid or expired (sign-in on) |
| 503 | `auth_unavailable` | the identity service's keys can't be fetched to check the token |
| 404 | `game_not_found` | also someone else's run |
| 409 | `illegal_action` | the game doesn't allow this now; nothing changed |
| 409 | `game_over` | the run is over |
| 409 | `version_conflict` | `expected_version` is not the run's version (`current_version` is given) |
| 422 | `invalid_settings`, `invalid_request` | bad settings or a body that doesn't match the schema |
| 403 | `debug_disabled` | |

Numbers too large for JSON (the game shows them as `naneinf`, very late in an
endless run) are sent as `null`.

### Sprites

The catalog gives, for every card, blind, tag, seal and sticker, its sprite
sheet (`atlas`) and its cell (`pos`). `atlases` maps each sheet to its file in
the game's `resources/textures/1x` (or `2x`) folder and its cell size. The API
does not serve the game's textures: a front end loads them from a copy of the
game.

## Settings

| Variable | Default | |
|---|---|---|
| `BALATRO_API_DATABASE_URL` | `postgresql://balatro:balatro@127.0.0.1:55433/balatro` (`make db`) | A PostgreSQL URL, or `memory` |
| `BALATRO_API_CORS_ORIGINS` | `*` | Comma-separated origins |
| `BALATRO_API_CACHE_SIZE` | `256` | Runs kept in memory; the others are rebuilt from their commands when needed |
| `BALATRO_API_DEBUG_COMMANDS` | off | Enables `POST /games/{id}/debug` |
| `BALATRO_API_HOST`, `BALATRO_API_PORT` | `127.0.0.1`, `8000` | For `balatro-api` |
| `BALATRO_API_AUTH_JWKS_URL` | unset (sign-in off) | The identity service's `/.well-known/jwks.json` |
| `BALATRO_API_AUTH_ISSUER` | | Required with the JWKS URL: the identity service's `PUBLIC_URL`, exactly |
| `BALATRO_API_AUTH_AUDIENCE` | `balatro` | The identity service's `JWT_AUDIENCE` |
| `BALATRO_API_ADMINS` | none | Account ids that may rebuild runs from a history, besides the roles (below); for a server without roles yet |

## Docker

```
docker build --network host -t balatro-api .
docker run -p 8000:8000 -e BALATRO_API_DATABASE_URL=postgresql://... balatro-api
```

The image listens on `0.0.0.0:8000` and keeps the runs in the PostgreSQL
database of `BALATRO_API_DATABASE_URL` (it makes its tables on start); the
settings above apply. `--network host` lets the
build download through this machine's own connection: behind a VPN whose MTU
is smaller than Docker's bridge (WireGuard: 1420), downloads from the bridge
stall. To run it with the front end, see BalatroFrontEnd's
`docker-compose.yml`.

## Roles

Access tokens name the account's roles (the identity service's `roles`
claim). `application/permissions.py` says what they allow here:

| Role | |
|---|---|
| `tester` | debug commands (`POST /games/{id}/debug`) on their own runs, even on a server without them; those runs don't count for statistics |
| `developer` | the same, and rebuilding runs from histories (`POST /games/import`), to replay bug reports |
| `admin` | everything |

## Storage

Runs live in PostgreSQL: one row per run and one per command (see
`docs/architecture.md`). The tables are made and upgraded by numbered
migrations when the server starts. `make db` starts the database of
BalatroFrontEnd's compose file (`api-db`, on `127.0.0.1:55433`).

Before PostgreSQL the runs were in a SQLite file. To copy them over, once:

```
python -m balatro_api.manage import-sqlite /data/balatro.db     # in Docker:
docker compose exec api python -m balatro_api.manage import-sqlite /data/balatro.db
```

Each imported run is replayed for its statistics. `python -m
balatro_api.manage rebuild-stats` replays every run again, after an engine
release that counts statistics differently.

## Statistics

`GET /stats/me` (the game's Profile > Stats), `GET /leaderboards/{board}` and
`GET /stats/global` (see `docs/endpoints.md`). The engine records what each
run adds to the player's profile with the game's own functions; the API keeps
it with the run (`RunStats`, a cache like the run's progress) and adds it up.
As in the game, a run whose seed the player chose, or a challenge, doesn't
count; nor does a run that used debug commands.

## Deployment

`.github/workflows/ci-cd.yml` runs the tests, ruff, mypy and a Docker build on
every push and pull request on `main` and `dev`. A push or a merge to `main`
then deploys: the code is copied to the server over SSH and BalatroFrontEnd's
`docker-compose.yml` rebuilds and restarts the `api` service there, and the job
waits until it is healthy. The server's setup and the secrets (the same in both
repositories) are in BalatroFrontEnd's README, "Deployment".

## How it works

A run is stored as its settings and the list of commands the player made. The
engine is deterministic, so replaying the commands rebuilds exactly the same
game, and the command list *is* the run. Games in play are kept in memory, and
a run that isn't in memory is replayed. Each action is played on a copy of the
game, which replaces the run's game only once the run is saved. A refused
action therefore changes nothing, and two server processes can't both apply an
action to the same version.

The code follows a clean architecture (see `AGENTS.md`):

```
src/balatro_api/
  domain/           runs, settings, their rules and errors (pure Python)
  application/      use cases, their inputs and outputs (dto), the ports they need
  infrastructure/   adapters: engine/ (BalatroEngine), persistence/ (PostgreSQL, memory), system
  presentation/     http/ (FastAPI: routes, request schemas, error mapping)
  bootstrap.py      wires the adapters into the use cases
  main.py           the ASGI app
  manage.py         maintenance commands (import the old SQLite runs, rebuild stats)
```

## Development

```
uv sync
uv run pytest
uv run ruff check src tests
uv run mypy
```

To work against a local checkout of the engine instead of the pinned version,
install it over the pinned one and keep uv from syncing it back:
`uv pip install -e ../BalatroEngine`, then `uv run --no-sync pytest`. A plain
`uv sync` returns to the pinned version.

## Legal

Balatro is © LocalThunk (published by Playstack). This is an unofficial fan
project, not affiliated with or endorsed by them. It contains none of the
game's code or assets.
