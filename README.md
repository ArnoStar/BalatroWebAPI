# BalatroWebAPI

An HTTP API to play Balatro runs, built for a front end. The game logic is
[BalatroEngine](https://github.com/ArnoStar/BalatroEngine)'s, which reproduces
Balatro 1.0.1o exactly: the same seed and the same choices give the same run
as in the original game. This service never reimplements a rule; it stores
runs, translates requests and shows the player what the game would show.

```
uv sync
uv run balatro-api                      # http://127.0.0.1:8000 (docs at /docs)
```

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
| `card_flipped`, `card_removed` | a card turns over, a card leaves the game |
| `hand` | the scoring panel: `hand`, `level`, `chips`, `mult`, `hand_score` (only what changes) |
| `card_text` | a pop-up over a card: `effect` (`chips`, `mult`, `x_mult`, `dollars`, `again`, `debuffed`, `message` ...) and `amount` |
| `hand_scored` | the hand's chips, mult and score, and the round score after it |
| `round_score`, `dollars`, `status_text` | the round score is set, money changes, text over the play area |

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
| 404 | `game_not_found` | |
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
| `BALATRO_API_DATABASE` | `balatro.db` | A SQLite file, or `memory` |
| `BALATRO_API_CORS_ORIGINS` | `*` | Comma-separated origins |
| `BALATRO_API_CACHE_SIZE` | `256` | Runs kept in memory; the others are rebuilt from their commands when needed |
| `BALATRO_API_DEBUG_COMMANDS` | off | Enables `POST /games/{id}/debug` |
| `BALATRO_API_HOST`, `BALATRO_API_PORT` | `127.0.0.1`, `8000` | For `balatro-api` |

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
  infrastructure/   adapters: engine/ (BalatroEngine), persistence/ (SQLite, memory), system
  presentation/     http/ (FastAPI: routes, request schemas, error mapping)
  bootstrap.py      wires the adapters into the use cases
  main.py           the ASGI app
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
