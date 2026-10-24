# Getting started

## Run the server

You need Python 3.12 or later and [uv](https://docs.astral.sh/uv/).

```
git clone https://github.com/ArnoStar/BalatroWebAPI.git
cd BalatroWebAPI
uv sync
uv run balatro-api
```

The server listens on `http://127.0.0.1:8000`. Two pages come with it:

- `http://127.0.0.1:8000/docs`: interactive documentation (Swagger UI) where
  every endpoint can be tried.
- `http://127.0.0.1:8000/openapi.json`: the OpenAPI 3.1 schema, from which a
  front end can generate typed clients.

Runs are stored in `balatro.db` in the current directory, so they survive a
restart. These environment variables change the setup:

| Variable | Default | Meaning |
|---|---|---|
| `BALATRO_API_DATABASE` | `balatro.db` | Path of the SQLite file, or `memory` to keep runs in memory only |
| `BALATRO_API_CORS_ORIGINS` | `*` | Origins allowed to call the API from a browser, comma-separated (e.g. `http://localhost:5173`) |
| `BALATRO_API_CACHE_SIZE` | `256` | How many runs keep their game in memory. Others are rebuilt from their history on the next request (slower, same result) |
| `BALATRO_API_DEBUG_COMMANDS` | off | `1` enables `POST /games/{id}/debug` (give money, add jokers, force a boss...), for testing a front end |
| `BALATRO_API_HOST`, `BALATRO_API_PORT` | `127.0.0.1`, `8000` | Where `balatro-api` listens |
| `BALATRO_API_AUTH_JWKS_URL` | unset | The identity service's key set (`http://127.0.0.1:8001/.well-known/jwks.json`): turns sign-in on |
| `BALATRO_API_AUTH_ISSUER` | | With sign-in: the identity service's `PUBLIC_URL` (`http://localhost:8001`) |
| `BALATRO_API_AUTH_AUDIENCE` | `balatro` | With sign-in: the tokens' audience |

By default the server runs **without sign-in**: anyone can call it, and every
caller is the same player. To play as real players, run BalatroIndentityService
(`make services && make run` there, on port 8001), set the first two auth
variables, and send its access tokens:

```
TOKEN=$(curl -s -X POST localhost:8001/auth/login -H 'content-type: application/json' \
  -d '{"email": "me@example.com", "password": "..."}' | jq -r .access_token)
curl localhost:8000/api/v1/games -H "Authorization: Bearer $TOKEN"
```

You can also run it with any ASGI server, for example
`uv run uvicorn balatro_api.main:app --reload`.

## Play a hand with curl

Start a run. The seed is optional; without one, the server picks a random
seed, like an unseeded run in the game.

```
curl -s -X POST localhost:8000/api/v1/games \
     -H 'content-type: application/json' \
     -d '{"seed": "TESTSEED", "deck": "b_red", "stake": 1}'
```

The answer is a [`GameView`](models.md#gameview), in phase `blind_select`.
Keep its `id`:

```json
{
  "id": "ce4759d47e6d49b9b0586bc26f058b02",
  "version": 0,
  "phase": "blind_select",
  "ante": 1, "round": 0, "dollars": 4,
  "blind_select": {
    "on_deck": "Small",
    "choices": [
      {"slot": "Small", "key": "bl_small", "name": "Small Blind", "state": "Select", "chips": 300, "reward": 3,
       "skip_tag": {"key": "tag_economy", "name": "Economy Tag", "orbital_hand": null}},
      {"slot": "Big", "key": "bl_big", "name": "Big Blind", "state": "Upcoming", "chips": 450.0, "reward": 4,
       "skip_tag": {"key": "tag_investment", "name": "Investment Tag", "orbital_hand": null}},
      {"slot": "Boss", "key": "bl_head", "name": "The Head", "state": "Upcoming", "chips": 600, "reward": 5,
       "skip_tag": null}
    ],
    "boss_reroll_cost": null
  },
  "actions": [{"type": "select_blind", ...}, {"type": "skip_blind", ...}],
  ...
}
```

Play the Small Blind:

```
ID=ce4759d47e6d49b9b0586bc26f058b02
curl -s -X POST localhost:8000/api/v1/games/$ID/actions \
     -H 'content-type: application/json' \
     -d '{"type": "select_blind", "expected_version": 0}'
```

The answer is an [`ActionResult`](models.md#actionresult): `game` is the new
`GameView` (phase `playing`, eight cards in `hand`) and `events` is what
happened on screen. The TESTSEED hand is:

| id | 35 | 37 | 25 | 47 | 8 | 4 | 17 | 3 |
|---|---|---|---|---|---|---|---|---|
| card | A♥ | K♥ | Q♦ | 9♠ | 9♣ | 5♣ | 5♦ | 4♣ |

Ask what five cards make, as the game shows while you select them:

```
curl -s -X POST localhost:8000/api/v1/games/$ID/preview \
     -H 'content-type: application/json' -d '{"cards": [35, 37, 25, 47, 8]}'
```

```json
{"selected": [35, 37, 25, 47, 8], "hand": "Pair", "display_name": "Pair", "level": 1,
 "chips": 10, "mult": 2, "scoring": [47, 8], "not_allowed": false, "hidden": false}
```

Play them:

```
curl -s -X POST localhost:8000/api/v1/games/$ID/actions \
     -H 'content-type: application/json' \
     -d '{"type": "play", "cards": [35, 37, 25, 47, 8], "expected_version": 1}'
```

The pair of nines scores (10 + 9 + 9) × 2 = 56. In the answer,
`game.round_score` is `56`, `game.last_hand` is
`{"hand": "Pair", "chips": 28, "mult": 2, "score": 56}`, and `events` includes
the two `+9` pop-ups and a `hand_scored` event. The same seed and the same
cards give 56 in the original game too.

## Next

- [Front-end flows](flows.md) walks through every screen.
- [Endpoints](endpoints.md) and [Data models](models.md) are the reference.
