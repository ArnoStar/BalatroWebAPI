# Endpoints

All endpoints are under `/api/v1` and exchange JSON (`application/json`).
Errors use the [problem details](#errors) format. The schemas of the objects
named here are in [Data models](models.md).

| Method | Path | Summary |
|---|---|---|
| `GET` | [`/health`](#get-health) | Is the server up, and which versions it runs |
| `GET` | [`/catalog`](#get-catalog) | Static game data: names, prices, sprites |
| `POST` | [`/games`](#post-games) | Start a run |
| `GET` | [`/games`](#get-games) | List runs |
| `GET` | [`/games/{id}`](#get-gamesid) | The run as the player sees it |
| `DELETE` | [`/games/{id}`](#delete-gamesid) | Delete a run |
| `GET` | [`/games/{id}/actions`](#get-gamesidactions) | What the player can do now |
| `POST` | [`/games/{id}/actions`](#post-gamesidactions) | Act |
| `POST` | [`/games/{id}/preview`](#post-gamesidpreview) | The poker hand selected cards make |
| `GET` | [`/games/{id}/history`](#get-gamesidhistory) | The run's settings and commands |
| `POST` | [`/games/{id}/debug`](#post-gamesiddebug) | Test helpers (when enabled) |

`GET /` redirects to `/docs`, the interactive documentation.
`GET /openapi.json` is the machine-readable schema.

---

## Authentication

When the server runs with sign-in (`GET /health` gives `"auth": "required"`),
every `/games` route needs an access token from the identity service
(BalatroIndentityService):

```
Authorization: Bearer eyJhbGciOiJSUzI1NiIs...
```

Without a token, or with an invalid or expired one, the answer is
`401 unauthenticated` with a `WWW-Authenticate: Bearer` header. The client then
refreshes its token at the identity service and tries again. A player only
sees their own runs: another player's run is `404 game_not_found`.
`/health` and `/catalog` are public.

With sign-in off (`"auth": "off"`), the header is ignored and everyone is the
same player.

---

## `GET /health`

Returns `200` with the versions the server runs, and whether it needs a
signed-in player.

```json
{"status": "ok", "api_version": "0.1.0", "engine_version": "0.3.0", "game_version": "1.0.1o-FULL", "auth": "required"}
```

`game_version` is the Balatro version whose logic the engine reproduces.
`auth` is `required` or `off` (see [Authentication](#authentication)).

---

## `GET /catalog`

Returns `200` with a [`Catalog`](models.md#catalog): every deck, stake,
challenge, joker, Tarot, Planet, Spectral, voucher, booster pack, enhancement,
edition, seal, sticker, tag, blind, poker hand and playing card, with its name,
price, numbers and sprite. It also lists the sprite sheets (`atlases`).

The catalog never changes while the server runs. Fetch it once at start-up.
The response carries an `ETag` and `Cache-Control: public, max-age=3600`.
Send the ETag back in `If-None-Match` to get `304 Not Modified` without a body.

| Status | When |
|---|---|
| 200 | the catalog |
| 304 | `If-None-Match` matches the current ETag |

Excerpt:

```json
{
  "game_version": "1.0.1o-FULL",
  "engine_version": "0.3.0",
  "jokers": [
    {"key": "j_joker", "name": "Joker", "set": "Joker", "cost": 2, "rarity": 1, "config": {"mult": 4},
     "sprite": {"atlas": "Joker", "pos": {"x": 0, "y": 0}, "soul_pos": null}, "requires": null}
  ],
  "atlases": {"Joker": {"file": "Jokers.png", "px": 71, "py": 95, "frames": null}},
  ...
}
```

How to use the sprites is described in [Rendering](rendering.md).

---

## `POST /games`

Starts a run and plays it to its first decision (the blind select screen).

**Body**: [`NewGameRequest`](models.md#newgamerequest)

| Field | Type | Default | |
|---|---|---|---|
| `seed` | string or null | null | 1 to 8 letters or digits. Lowercase is upper-cased and `0` becomes `O`, as the game reads typed seeds. Null picks a random 8-character seed. |
| `deck` | string | `"b_red"` | A deck key from the catalog (`b_red`, `b_blue`, ..., `b_erratic`) or its short name (`red`, `blue`, ...) |
| `stake` | integer 1-8 | 1 | 1 White, 2 Red, 3 Green, 4 Black, 5 Blue, 6 Purple, 7 Orange, 8 Gold |
| `challenge` | string or null | null | A challenge id from the catalog (`c_omelette_1`, ...). A challenge sets its own deck and is played on White Stake, so `deck` and `stake` are then ignored. |
| `game_speed` | number | 1 | The game's speed setting: 0.5, 1, 2 or 4. It decides when animated effects land, and a few interactions in the game depend on that (see [Architecture](architecture.md#timing)). Keep 1 unless you want to match a player who uses another speed. |

**Response**: `201 Created` with the [`GameView`](models.md#gameview), and a
`Location` header with the run's URL.

| Status | `code` | When |
|---|---|---|
| 201 | | the run was created |
| 422 | `invalid_settings` | unknown deck or challenge, bad seed, stake or speed |
| 422 | `invalid_request` | the body doesn't match the schema |

```
POST /api/v1/games
{"seed": "TESTSEED", "deck": "b_red", "stake": 1}

201 Created
Location: /api/v1/games/ce4759d47e6d49b9b0586bc26f058b02
{"id": "ce4759d47e6d49b9b0586bc26f058b02", "version": 0, "phase": "blind_select", ...}
```

The settings the run actually uses come back in `settings`, after
normalization (seed upper-cased, deck key, challenge deck and stake).

---

## `GET /games`

Lists runs, most recently played first, as
[`GameSummaryView`](models.md#gamesummaryview)s. Use it for a "continue" menu.

| Query | Default | |
|---|---|---|
| `limit` | 50 | 1 to 200 |
| `offset` | 0 | for paging |

```json
[{"id": "ce4759d47e6d49b9b0586bc26f058b02", "version": 7,
  "settings": {"seed": "TESTSEED", "deck": "b_red", "stake": 1, "challenge": null, "game_speed": 1.0},
  "phase": "pack", "ante": 1, "round": 1, "dollars": 46, "won": false,
  "created_at": "2026-10-23T18:15:58.851697Z", "updated_at": "2026-10-23T18:15:58.961100Z"}]
```

---

## `GET /games/{id}`

Returns `200` with the [`GameView`](models.md#gameview): everything the player
can see now, and `actions`, what they can do.

| Status | `code` | |
|---|---|---|
| 200 | | |
| 404 | `game_not_found` | |

Reading a run never changes it. Call it whenever the front end needs to
resync, for example on page load, after a `version_conflict`, or after a
network error.

---

## `DELETE /games/{id}`

Deletes the run and its history. Returns `204 No Content`, or `404
game_not_found`.

---

## `GET /games/{id}/actions`

Returns `200` with the list of [`LegalAction`](models.md#legalaction)s: what
the game allows right now. It is the same list as `GameView.actions`.

```json
[{"type": "buy", "card": 53, "area": "shop", "use": false, "cost": 5, ...},
 {"type": "buy", "card": 55, "area": "vouchers", "use": false, "cost": 10, ...},
 {"type": "buy", "card": 56, "area": "boosters", "use": false, "cost": 4, ...},
 {"type": "reroll", "cost": 5, ...},
 {"type": "end_shop", ...}]
```

(Fields that don't apply to an action are `null`. They are left out above.)

---

## `POST /games/{id}/actions`

Applies one player action. The server then runs the game until it waits for
the player again, and returns the result.

**Body**: one [action](models.md#actions), chosen by `type`, with an optional
`expected_version`.

| `type` | Fields | |
|---|---|---|
| `select_blind` | | Play the blind on deck |
| `skip_blind` | | Skip the Small or Big blind and take its tag |
| `reroll_boss` | | Reroll the boss ($10; needs the Director's Cut or Retcon voucher) |
| `play` | `cards` | Play these hand cards |
| `discard` | `cards` | Discard these hand cards |
| `sort` | `mode`: `"rank"` or `"suit"` | The hand's sort buttons. The choice sticks: new cards are sorted the same way |
| `cash_out` | | Collect the round's money and go to the shop |
| `buy` | `card`, `use` (default false) | Buy a shop card, redeem the voucher, or open a booster pack. With `use: true`, buy a consumable and use it at once |
| `reroll` | | Reroll the shop |
| `end_shop` | | Leave the shop (Next Round) |
| `use` | `card`, `targets` | Use a consumable. `targets` are the hand cards it acts on (Tarot and Spectral cards that need a selection) |
| `sell` | `card` | Sell a joker or a consumable |
| `move` | `card`, `to` | Move a joker, consumable or hand card to position `to` (0 = leftmost) |
| `pick` | `card`, `targets` | Take a card from the open booster pack, or use it if it's a consumable (`targets` as for `use`) |
| `skip_pack` | | Skip the rest of the booster pack |

`cards`, `card` and `targets` are card **ids**
([`CardView.id`](models.md#cardview)).

`expected_version` is optional. When it is given and the run is not at that
version, the action is refused with `409 version_conflict`.

**Response**: `200` with an [`ActionResult`](models.md#actionresult):
`game` is the new `GameView` and `events` the
[timeline](animations.md) of what the player saw happen.

| Status | `code` | When |
|---|---|---|
| 200 | | the action was applied |
| 404 | `game_not_found` | |
| 409 | `illegal_action` | the game doesn't allow this action now (wrong screen, can't afford it, no space, too many cards, a card that isn't there...). The run is unchanged. `detail` says why. |
| 409 | `game_over` | the run is over |
| 409 | `version_conflict` | `expected_version` is not the current version (`current_version` is in the body) |
| 422 | `invalid_request` | unknown `type`, a missing field, a wrong type |

```
POST /api/v1/games/{id}/actions
{"type": "play", "cards": [35, 37, 25, 47, 8], "expected_version": 1}

200 OK
{"game": {"version": 2, "round_score": 56, "hands_left": 3, ...},
 "events": [{"type": "card_moved", "t": 0.55, "card": 35, "to": "play"}, ...]}
```

What can be sent when, and how it plays out, is described screen by screen in
[Front-end flows](flows.md).

---

## `POST /games/{id}/preview`

Says what the selected hand cards make, as the game shows above the hand while
cards are selected: the poker hand, its level, chips and mult, the cards that
would score, and whether the boss blind forbids it. It changes nothing; call
it as often as the selection changes.

**Body**: `{"cards": [card ids]}`. A card forced into the selection by
Cerulean Bell counts as selected even if you leave it out.

**Response**: `200` with a [`HandPreview`](models.md#handpreview).

```json
{"selected": [35, 37, 25, 47, 8], "hand": "Pair", "display_name": "Pair", "level": 1,
 "chips": 10, "mult": 2, "scoring": [47, 8], "not_allowed": false, "hidden": false}
```

| Status | `code` | When |
|---|---|---|
| 200 | | |
| 404 | `game_not_found` | |
| 409 | `illegal_action` | not in the `playing` phase, a card not in the hand, a card twice, more than 5 cards |

- **Nothing selected**: `hand` is `null`.
- **A face-down card selected**: `hidden` is `true` and the hand isn't given.
  The game shows `????` then.
- **A forbidden hand**: `not_allowed: true` means the boss blind forbids this
  hand (The Eye, The Mouth, The Psychic...). Playing it scores nothing.

---

## `GET /games/{id}/history`

Returns `200` with a [`HistoryView`](models.md#historyview): the run's settings
and every accepted command, in order, in the engine's own format, where cards
are positions in their area rather than ids.

```json
{"id": "ce4759d47e6d49b9b0586bc26f058b02", "version": 7, "engine_version": "0.3.0",
 "settings": {"seed": "TESTSEED", "deck": "b_red", "stake": 1, "challenge": null, "game_speed": 1.0},
 "commands": [{"cmd": "select_blind"}, {"cmd": "play", "cards": [0, 1, 2, 3, 4]}, {"cmd": "discard", "cards": [0]},
              {"cmd": "cheat", "win": true}, {"cmd": "cash_out"}, {"cmd": "cheat", "dollars": 50},
              {"cmd": "buy", "area": "shop_booster", "index": 0}]}
```

Replaying these commands with BalatroEngine (`Game(...).start_run()`, then
`G.do(command)` for each) rebuilds the run exactly. This is useful for bug
reports, and for checking a run against the original game with the engine's
oracle tools.

---

## `POST /games/import`

Rebuilds a run from its history, as a new run of the caller's: to see a bug
report's run again (BalatroBugReportService keeps the history; the game's
`/play/?report=<id>` calls this). Allowed for the accounts in
`BALATRO_API_ADMINS`, or anyone on a server with debug commands; otherwise
`403 import_forbidden`.

**Body**: a history as `GET /games/{id}/history` gives it (extra fields are
ignored), possibly with fewer commands: `{"settings": {"seed", "deck",
"stake", "challenge", "game_speed"}, "commands": [...]}`. The commands are
replayed with the engine; the first that doesn't replay is `409
illegal_action` ("command #n doesn't replay"). **Response** `201`: the
GameView, at version = the number of commands. The new run is seeded and
counts as a debug run: it never counts for statistics.

---

## `POST /games/{id}/debug`

Applies a test helper. It exists only to help build and test a front end, for
example to reach a late ante, try a given joker, or force a boss. It returns
`403 debug_disabled` unless the server runs with
`BALATRO_API_DEBUG_COMMANDS=1`. Helpers are recorded in the history like
actions, so the run still replays.

**Body**: `{"command": {...}, "expected_version": null}`, where `command` is
one of:

| Command | Effect |
|---|---|
| `{"cmd": "cheat", "dollars": 100}` | set the money |
| `{"cmd": "cheat", "ante": 8}` | set the ante |
| `{"cmd": "cheat", "boss": "bl_hook"}` | set this ante's boss blind (a blind key from the catalog) |
| `{"cmd": "cheat", "win": true}` | beat the current blind now (in the `playing` phase) |
| `{"cmd": "add_joker", "key": "j_blueprint", "edition": "negative"}` | add a joker or a consumable (any center key; `edition` optional: `foil`, `holo`, `polychrome`, `negative`) |
| `{"cmd": "add_tag", "key": "tag_charm"}` | add a tag (`orbital_hand` sets an Orbital Tag's hand) |
| `{"cmd": "add_voucher", "key": "v_retcon"}` | redeem a voucher for free |

None of them consumes randomness. **Response**: as for
[`POST /actions`](#post-gamesidactions). An unknown command or key gives
`409 illegal_action`.

---

## Statistics

As in the game, statistics count only runs whose seed the player didn't
choose (`POST /games` without `seed`) and that aren't challenges; here, runs
that used a debug command don't count either (`counted` in `GET /games`).
Each run's part comes from the engine, which records what it adds to the
player's profile with the game's own functions.

### `GET /stats/me`

The caller's profile statistics, like the game's Profile > Stats screens:
`runs` (total, counted, won, lost, in progress), `high_scores` (best hand,
highest ante and round, most money, bosses in a row, best and current win
streak, most played hand), `career` (the game's career stats added up),
`hands`, `jokers` (won rounds held, wins, losses, best stake won),
`consumables`, `vouchers`, `decks` (per stake), and `activity` (runs started
on each of the last 30 days, UTC).

### `GET /leaderboards/{board}?deck=&stake=&limit=50`

`board`: `best_hand`, `highest_ante`, `highest_round`, `most_money`,
`boss_streak` or `wins`. Each player's best counted run on that board (for
`wins`, their number of won runs), best first; equal values share a rank and
are listed by who reached them first. `deck` (a deck key) and `stake` (1-8)
keep only those runs. `entries` are the top `limit`; `you` is the caller's
entry wherever it ranks (`null` when not on the board). Players appear by
their display name only (`null` without one), never by id or run.

### `GET /stats/global`

Everyone's counted runs together: players, runs, wins and losses, hands and
cards played, money earned, the best hand and the highest ante, and runs per
deck and per stake, the 20 most kept jokers and the poker hands played.

---

## Request ids

Every response has an `X-Request-ID`: the one the client sent (8 to 64
letters, digits, `.`, `_`, `-`), or a new one. The server logs one line per
request with it (`balatro_api.requests`: method, path, status, time), and a
`500` answer carries it as `request_id`. The game sends its own and records
it, so a bug report points at the server's log lines.

---

## Errors

Every error is a problem details object
([RFC 9457](https://www.rfc-editor.org/rfc/rfc9457)) with the content type
`application/problem+json`. Switch on `code`, which is stable, and show
`detail` to the user if you like.

```json
{"type": "https://balatro-api/errors/illegal_action", "title": "Conflict", "status": 409,
 "detail": "not at the round evaluation", "code": "illegal_action"}
```

| Status | `code` | Meaning | Extra fields |
|---|---|---|---|
| 401 | `unauthenticated` | no access token, or an invalid or expired one (sign-in on) | |
| 403 | `debug_disabled` | debug commands are off on this server | |
| 404 | `game_not_found` | no run with this id (or it is another player's) | |
| 409 | `illegal_action` | the game doesn't allow this action now; nothing changed | |
| 409 | `game_over` | the run is over | |
| 409 | `version_conflict` | the run has moved on since the version the client acted on | `expected_version`, `current_version` |
| 422 | `invalid_settings` | the run can't be started with these settings | |
| 422 | `invalid_request` | the body or the query doesn't match the schema | `errors`: `[{loc, msg, type}]` |
| 500 | `internal_error` | a server bug; nothing changed | |
| 503 | `auth_unavailable` | the identity service's keys can't be fetched to check the token | |

```json
{"type": "https://balatro-api/errors/version_conflict", "title": "Conflict", "status": 409,
 "detail": "the game is at version 7, not 0", "code": "version_conflict", "expected_version": 0, "current_version": 7}

{"type": "https://balatro-api/errors/invalid_request", "title": "Unprocessable Content", "status": 422,
 "detail": "the request doesn't match the schema", "code": "invalid_request",
 "errors": [{"loc": ["body", "play", "cards"], "msg": "Field required", "type": "missing"}]}
```

## CORS

Browsers may call the API from the origins in `BALATRO_API_CORS_ORIGINS`
(default: any). The `ETag`, `Location` and `WWW-Authenticate` headers are
exposed to scripts, and `Authorization` is allowed.
