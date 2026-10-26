# Data models

Every JSON object the API sends or accepts, field by field. Field names are
snake_case. Unless stated otherwise:

- **Numbers** are integers or decimals (`450.0`), as the game computes them.
  A number too large for JSON (the game shows it as `naneinf`, very late in an
  endless run) is sent as `null`.
- **Nullable fields** are always present, with `null` when they don't apply.
- **Keys** (`j_joker`, `bl_hook`, `tag_charm`...) are the game's own
  identifiers. Look them up in the [catalog](#catalog) for names and sprites.

The OpenAPI schema (`/openapi.json`) describes the same objects for code
generators.

Contents: [requests](#requests) · [GameView](#gameview) ·
[cards](#cards) · [blinds](#blinds) · [shop, pack, round evaluation](#shop-pack-and-round-evaluation) ·
[run information](#run-information) · [LegalAction](#legalaction) ·
[ActionResult and events](#actionresult) · [HandPreview](#handpreview) ·
[GameSummaryView, HistoryView](#gamesummaryview) · [Catalog](#catalog)

---

## Requests

### NewGameRequest

Body of `POST /games`.

| Field | Type | Default | |
|---|---|---|---|
| `seed` | string \| null | null | `^[A-Za-z0-9]{1,8}$`; null for a random seed |
| `deck` | string | `"b_red"` | deck key or short name (`red`, `blue`, `yellow`, `green`, `black`, `magic`, `nebula`, `ghost`, `abandoned`, `checkered`, `zodiac`, `painted`, `anaglyph`, `plasma`, `erratic`) |
| `stake` | integer | 1 | 1 (White) to 8 (Gold) |
| `challenge` | string \| null | null | challenge id; sets the deck, and the stake to 1 |
| `game_speed` | number | 1 | 0.5, 1, 2 or 4 |

### Actions

Body of `POST /games/{id}/actions`: an object with a `type`. Each type
accepts only its own fields (others are rejected), plus `expected_version`.

| `type` | Fields |
|---|---|
| `select_blind`, `skip_blind`, `reroll_boss` | none |
| `play`, `discard` | `cards`: card ids (integers) |
| `sort` | `mode`: `"rank"` (default) or `"suit"` |
| `cash_out` | none |
| `buy` | `card`: id; `use`: boolean, default false |
| `reroll`, `end_shop` | none |
| `use` | `card`: id; `targets`: card ids or null |
| `sell` | `card`: id |
| `move` | `card`: id; `to`: integer ≥ 0 |
| `pick` | `card`: id; `targets`: card ids or null |
| `skip_pack` | none |

| Common field | Type | |
|---|---|---|
| `expected_version` | integer \| null | The `GameView.version` the action was chosen from. If the run is at another version, the action is refused with `409 version_conflict`. |

### PreviewRequest

Body of `POST /games/{id}/preview`: `{"cards": [card ids]}`.

### DebugRequest

Body of `POST /games/{id}/debug`: `{"command": {...}, "expected_version": null}`.
The commands are listed in [Endpoints](endpoints.md#post-gamesiddebug).

---

## GameView

A run as the player sees it. It is returned by `GET /games/{id}`,
`POST /games`, and as `game` in every `ActionResult`.

| Field | Type | |
|---|---|---|
| `id` | string | the run's id |
| `version` | integer | the number of accepted actions; send it back as `expected_version` |
| `settings` | [SettingsView](#settingsview) | what the run was started with |
| `phase` | string | the screen: `blind_select`, `playing`, `round_eval`, `shop`, `pack`, `game_over` |
| `state` | string | the game's own state name: `BLIND_SELECT`, `SELECTING_HAND`, `ROUND_EVAL`, `SHOP`, `TAROT_PACK`, `PLANET_PACK`, `SPECTRAL_PACK`, `STANDARD_PACK`, `BUFFOON_PACK`, `GAME_OVER` |
| `won` | boolean | the run has beaten the ante 8 boss. It goes on in endless mode until it is lost. |
| `ante` | integer | the current ante |
| `round` | integer | rounds started so far (1 during the first blind) |
| `dollars` | number | money (can be negative with Credit Card) |
| `hands_left` | integer | hands left this round |
| `discards_left` | integer | discards left this round |
| `hand_size` | integer | how many cards the hand holds |
| `joker_slots` | integer | joker slots |
| `consumable_slots` | integer | consumable slots |
| `round_score` | number | the score so far this round |
| `blind` | [BlindView](#blindview) \| null | the blind being played (phases `playing` and `round_eval`) |
| `blind_select` | [BlindSelectView](#blindselectview) \| null | the three blinds of the ante (phase `blind_select`) |
| `hand` | [CardView](#cardview)[] | the hand, left to right |
| `jokers` | CardView[] | the jokers, left to right |
| `consumables` | CardView[] | the consumables, left to right |
| `deck` | [DeckView](#deckview) | the cards left in the deck |
| `discard_count` | integer | cards in the discard pile this round |
| `shop` | [ShopView](#shopview) \| null | phase `shop` (null while a pack is open, even one bought in the shop) |
| `pack` | [PackView](#packview) \| null | phase `pack` |
| `round_eval` | [RoundEvalView](#roundevalview) \| null | phase `round_eval` |
| `tags` | [TagView](#tagview)[] | tags held, oldest first |
| `vouchers` | string[] | voucher keys redeemed, in order |
| `poker_hands` | [PokerHandView](#pokerhandview)[] | every poker hand, best first (Flush Five ... High Card) |
| `last_hand` | [HandScore](#handscore) \| null | the last hand played this run |
| `info` | [RunInfo](#runinfo) | values card descriptions refer to |
| `actions` | [LegalAction](#legalaction)[] | what can be done now |

### SettingsView

| Field | Type | |
|---|---|---|
| `seed` | string | as the game uses it (upper-case, `0` → `O`) |
| `deck` | string | deck key (`b_challenge` for most challenges) |
| `stake` | integer | 1-8 |
| `challenge` | string \| null | challenge id |
| `game_speed` | number | 0.5, 1, 2 or 4 |
| `seeded` | boolean | the player chose the seed: the run doesn't count for statistics |

---

## Cards

### CardView

One card the player can see: a playing card, a joker, a consumable, a voucher
or a booster pack.

| Field | Type | |
|---|---|---|
| `id` | integer | unique in the run, and stable: the card keeps it in every area until it is destroyed |
| `kind` | string | `playing_card`, `joker`, `tarot`, `planet`, `spectral`, `voucher`, `booster` |
| `face_down` | boolean | the card is face down (The House, The Wheel, The Fish, The Mark, Amber Acorn). Then only `id`, `kind` and `selected` are given; every other field is `null` or `false`. |
| `key` | string \| null | the center key: `j_joker`, `c_fool`, `v_overstock_norm`, `p_arcana_normal_1`; for a playing card, its enhancement or `c_base` |
| `name` | string \| null | display name (`Joker`, `The Fool`, `Ace of Hearts`) |
| `rank` | string \| null | playing cards: `2`...`10`, `Jack`, `Queen`, `King`, `Ace` |
| `suit` | string \| null | playing cards: `Spades`, `Hearts`, `Clubs`, `Diamonds` |
| `card_key` | string \| null | playing cards: suit letter + rank (`H_A`, `S_T`, `D_7`), the key of its front sprite |
| `enhancement` | string \| null | playing cards: `m_bonus`, `m_mult`, `m_wild`, `m_glass`, `m_steel`, `m_stone`, `m_gold`, `m_lucky`, or null |
| `edition` | string \| null | `foil`, `holo`, `polychrome`, `negative`, or null |
| `seal` | string \| null | `Gold`, `Red`, `Blue`, `Purple`, or null |
| `stickers` | [Stickers](#stickers) \| null | jokers with stickers (higher stakes) |
| `rarity` | integer \| null | jokers: 1 Common, 2 Uncommon, 3 Rare, 4 Legendary |
| `debuffed` | boolean | the card is debuffed (by the boss blind, or a perishable joker that ran out) |
| `selected` | boolean | the card is selected (highlighted). After an action this is mostly a forced card. |
| `forced_selection` | boolean | Cerulean Bell: this card is always selected and is played with every hand |
| `cost` | number \| null | the price, for cards in the shop (`shop`, vouchers, boosters) |
| `sell_value` | number \| null | what selling gives, for jokers and consumables |
| `bonus_chips` | number \| null | playing cards: chips added for good (Hiker) |
| `ability` | object \| null | jokers: the values their effect keeps. See below. |

**`ability`** holds a joker's current numbers, for its description and
counters. Only those that are set are present:

| Key | |
|---|---|
| `mult`, `x_mult` | mult the joker gives or has built up (Ride the Bus, Hologram, ...) |
| `extra` | the joker's own parameters and counters: a number (e.g. Ice Cream's chips) or an object (e.g. Greedy Joker `{"s_mult": 3, "suit": "Diamonds"}`) |
| `extra_value` | extra sell value (Egg, Gift Card) |
| `caino_xmult`, `yorick_discards`, `invis_rounds`, `to_do_poker_hand`, `loyalty_remaining` | Canio, Yorick, Invisible Joker, To Do List, Loyalty Card |
| `perish_tally` | rounds left on a perishable joker |

Example, a playing card in hand and a joker in the shop:

```json
{"id": 35, "kind": "playing_card", "face_down": false, "key": "c_base", "name": "Ace of Hearts",
 "rank": "Ace", "suit": "Hearts", "card_key": "H_A", "enhancement": null, "edition": null, "seal": null,
 "stickers": null, "rarity": null, "debuffed": false, "selected": false, "forced_selection": false,
 "cost": null, "sell_value": null, "bonus_chips": null, "ability": null}

{"id": 53, "kind": "joker", "face_down": false, "key": "j_raised_fist", "name": "Raised Fist",
 "rank": null, "suit": null, "card_key": null, "enhancement": null, "edition": null, "seal": null,
 "stickers": null, "rarity": 1, "debuffed": false, "selected": false, "forced_selection": false,
 "cost": 5, "sell_value": null, "bonus_chips": null, "ability": {"mult": 0, "x_mult": 1, "extra_value": 0}}
```

### Stickers

| Field | Type | |
|---|---|---|
| `eternal` | boolean | can't be sold or destroyed |
| `perishable` | integer \| null | rounds left before the joker is debuffed (null: not perishable) |
| `rental` | boolean | costs $3 at the end of each round |

### DeckView

The cards left in the deck. The deck's order is hidden in the game, so the
cards are sorted (by suit: Spades, Hearts, Clubs, Diamonds, then by rank,
highest first) and have no id. Ids could let a client recognize a card that
is later drawn face down.

| Field | Type | |
|---|---|---|
| `remaining` | integer | cards left in the deck |
| `total` | integer | all the playing cards the run owns |
| `cards` | [DeckCardView](#deckcardview)[] | the cards left, sorted |

### DeckCardView

| Field | Type |
|---|---|
| `key` | string (enhancement or `c_base`) |
| `card_key` | string (`S_A`) |
| `rank`, `suit` | string |
| `enhancement`, `edition`, `seal` | string \| null |

---

## Blinds

### BlindSelectView

The blind select screen.

| Field | Type | |
|---|---|---|
| `on_deck` | `Small` \| `Big` \| `Boss` | the blind that `select_blind` plays and `skip_blind` skips |
| `choices` | [BlindChoiceView](#blindchoiceview)[] | the ante's three blinds |
| `boss_reroll_cost` | number \| null | 10 when the boss can be rerolled now (Director's Cut once per ante, or Retcon), else null |

### BlindChoiceView

| Field | Type | |
|---|---|---|
| `slot` | `Small` \| `Big` \| `Boss` | |
| `key` | string | blind key (`bl_small`, `bl_big`, `bl_hook`, ...) |
| `name` | string | |
| `state` | string | `Select` (on deck), `Upcoming`, `Current`, `Defeated`, `Skipped`, `Hide` |
| `chips` | number | the score needed |
| `reward` | number | dollars for beating it (0 when the stake removes the reward, e.g. the Small Blind from Red Stake up) |
| `skip_tag` | [TagView](#tagview) \| null | the tag skipping it gives (Small and Big only) |

### BlindView

The blind being played.

| Field | Type | |
|---|---|---|
| `key`, `name` | string | |
| `slot` | `Small` \| `Big` \| `Boss` \| null | |
| `chips` | number | the score needed |
| `reward` | number | dollars for beating it |
| `boss` | boolean | |
| `disabled` | boolean | its effect is disabled (Chicot, Luchador) |

### TagView

| Field | Type | |
|---|---|---|
| `key` | string | `tag_charm`, `tag_double`, ... |
| `name` | string | |
| `orbital_hand` | string \| null | an Orbital Tag's poker hand |

---

## Shop, pack and round evaluation

### ShopView

| Field | Type | |
|---|---|---|
| `jokers` | CardView[] | the shop's card slots: jokers, consumables, playing cards |
| `vouchers` | CardView[] | the ante's voucher (if not bought yet) |
| `boosters` | CardView[] | the two booster packs |
| `reroll_cost` | number | the next reroll's price (0 while free rerolls last) |
| `free_rerolls` | integer | free rerolls left this shop (Chaos the Clown) |

### PackView

An open booster pack.

| Field | Type | |
|---|---|---|
| `kind` | string | `tarot`, `planet`, `spectral`, `standard`, `buffoon` |
| `cards` | CardView[] | the cards to choose from |
| `choices_left` | integer | how many cards can still be taken |

For Tarot and Spectral packs, the hand is dealt so their targets can be
chosen. It is in `GameView.hand`.

### RoundEvalView

The cash-out screen after a blind is beaten.

| Field | Type | |
|---|---|---|
| `rows` | RoundEvalRow[] | the money rows, in screen order |
| `total` | number | what `cash_out` adds |

### RoundEvalRow

| Field | Type | |
|---|---|---|
| `kind` | string | `blind` (the blind's reward), `hands` (remaining hands), `discards` (remaining discards, Green Deck), `joker` (Golden Joker, Cloud 9, Rocket...), `tag` (Investment Tag), `interest` |
| `dollars` | number | |
| `key` | string \| null | the joker or tag that pays |

```json
{"rows": [{"kind": "blind", "dollars": 3, "key": null}, {"kind": "hands", "dollars": 3, "key": null}], "total": 6}
```

### HandScore

| Field | Type | |
|---|---|---|
| `hand` | string | poker hand played |
| `chips`, `mult` | number | final chips and mult |
| `score` | number | chips × mult (rounded down) |

### PokerHandView

| Field | Type | |
|---|---|---|
| `name` | string | `Flush Five`, ..., `High Card` (the key used everywhere) |
| `display_name` | string | the name shown |
| `level` | integer | |
| `chips`, `mult` | number | base chips and mult at this level |
| `played` | integer | times played this run |
| `visible` | boolean | the game lists it (secret hands appear once played) |

---

## Run information

### RunInfo

Values that card descriptions read, as the game's tooltips show them.

| Field | Type | |
|---|---|---|
| `probability_normal` | number | the numerator of "1 in N" chances: 1, doubled by each Oops! All 6s |
| `last_tarot_planet` | string \| null | the last Tarot or Planet used, which The Fool would create |
| `interest_amount` | number | dollars of interest per $5 |
| `interest_cap` | number | the most money interest counts (25, 50 with Seed Money, 100 with Money Tree) |
| `discount_percent` | number | shop discount (Clearance Sale, Liquidation) |
| `bankrupt_at` | number | how far into debt the run may go (Credit Card: -20) |
| `skips` | integer | blinds skipped (Throwback) |
| `hands_played` | integer | hands played this run |
| `unused_discards` | integer | discards left unused, summed over rounds (Garbage Tag) |
| `round_targets` | [RoundTargets](#roundtargets) | |

### RoundTargets

This round's targets, which change every round.

| Field | Type | Joker |
|---|---|---|
| `idol_rank`, `idol_suit` | string \| null | The Idol |
| `mail_rank` | string \| null | Mail-In Rebate |
| `ancient_suit` | string \| null | Ancient Joker |
| `castle_suit` | string \| null | Castle |
| `most_played_hand` | string \| null | The Ox (boss) |

---

## LegalAction

One thing the player can do now. Fill in what it leaves open and send it as an
[action](#actions). Fields that don't apply are `null`.

| Field | Type | |
|---|---|---|
| `type` | string | the action type |
| `card` | integer \| null | `buy`, `sell`, `use`, `pick`: the card |
| `area` | string \| null | where the card is: `shop`, `vouchers`, `boosters`, `jokers`, `consumables`, `pack`, `hand`. For `move`, the area that can be reordered. |
| `use` | boolean \| null | `buy`: true for the "buy and use" variant of a consumable |
| `mode` | string \| null | `sort`: `rank` or `suit` |
| `min_cards`, `max_cards` | integer \| null | `play`, `discard`: how many hand cards (1 to 5) |
| `min_targets`, `max_targets` | integer \| null | `use`, `pick`: how many hand cards the consumable needs selected (null: none) |
| `cost` | number \| null | `buy`, `reroll`, `reroll_boss`: the price |
| `value` | number \| null | `sell`: what it gives |

The list contains:

- **`select_blind`** and **`skip_blind`**: at blind select. `skip_blind` is
  listed only for the Small and Big blinds. **`reroll_boss`** appears when it
  can be afforded and is allowed.
- **`play`** and **`discard`**: while playing. `discard` only while discards
  are left. **`sort`** appears twice, once per mode.
- **`cash_out`**: at the round evaluation.
- **`buy`**: one entry per shop card that can be afforded and has room, one
  per voucher and booster that can be afforded, plus a `use: true` variant for
  a consumable that can be used now. Then **`reroll`** if it can be afforded,
  and **`end_shop`**.
- **`pick`**: one per pack card that can be taken (a joker needs a free slot;
  consumables that need targets list `min_targets`/`max_targets`), and
  **`skip_pack`**.
- **`use`**: one per consumable that can be used now. A consumable that needs
  targets is listed when targets can be chosen (playing, or a Tarot, Spectral
  or Planet pack); whether the chosen targets fit is checked when the action
  is sent.
- **`sell`**: one per joker and consumable that can be sold (not Eternal).
- **`move`**: one per area with at least two cards (`jokers`, `consumables`,
  `hand`). Choose `card` and `to` yourself.

---

## ActionResult

The response of `POST /games/{id}/actions` and `POST /games/{id}/debug`.

| Field | Type | |
|---|---|---|
| `game` | [GameView](#gameview) | the run after the action |
| `events` | Event[] | what the player saw happen, in order |

### Events

Every event has a `type` and `t`, the time in seconds (from the action's
start, at the run's game speed and 60 frames per second) at which the game
shows it. How to use them is explained in [Animations](animations.md).

| `type` | Fields | |
|---|---|---|
| `card_moved` | `card`, `to` (area: `deck`, `hand`, `play`, `discard`, `jokers`, `consumables`, `shop`, `vouchers`, `boosters`, `pack`) | a card arrives in an area |
| `card_flipped` | `card`, `face_down` (boolean), `view` (face up: the card's CardView as it ends the action) | a card turns over. Show the card as `view` says: a tarot or spectral may just have changed it, and it may end the action in the deck, which `game` doesn't list |
| `card_juiced` | `card` | the joker behind a scored or held card's effect wiggles (the effect's pop-up is on the playing card: Ancient Joker, Greedy Joker...) |
| `card_removed` | `card`, `area` | a card leaves the game (sold, used, destroyed, or a shop card when the shop closes) |
| `hand` | `hand`, `level`, `chips`, `mult`, `hand_score` | the scoring panel changes. Only changed values are given; `""` clears a value, `"?"` hides it (face-down cards selected) |
| `card_text` | `card`, `effect`, `amount`, `message`, `held`, `edition` | a pop-up over a card |
| `hand_scored` | `hand`, `chips`, `mult`, `score`, `round_score` | the hand's final chips and mult, its score, and the round score after it |
| `round_score` | `chips` | the round score is set (reset to 0 at cash out) |
| `dollars` | `amount`, `total` | money changes by `amount`, to `total` |
| `status_text` | `text` | text over the play area (`Not Allowed!`) |

`card_text.effect` is one of:

| `effect` | Shows | `amount` |
|---|---|---|
| `chips` | `+N` (blue) | chips added |
| `mult` | `+N Mult` (red) | mult added (`held: true` for a card held in hand) |
| `x_mult` | `XN Mult` | mult multiplier |
| `dollars` | `$N` | money |
| `again` | `Again!` | a retrigger (Red Seal, Hack, Sock and Buskin, Dusk...) |
| `debuffed` | `Debuffed!` | a debuffed card scores nothing |
| `swap` | `Swapped!` | chips and mult swapped |
| `message` | a joker's message (`Upgrade!`, `Saved!`, ...) | `message` gives a key when known: `plus_planet`, `plus_tarot`, `boss_disabled`, `disabled`, `remaining`, `edition`; otherwise null |

`edition: true` marks a pop-up that comes from the card's edition (Foil,
Holographic, Polychrome).

---

## HandPreview

The response of `POST /games/{id}/preview`.

| Field | Type | |
|---|---|---|
| `selected` | integer[] | the selection, including a forced card |
| `hand` | string \| null | the poker hand (null: nothing selected, or `hidden`) |
| `display_name` | string \| null | the name shown: as `hand`, except `Royal Flush` for an ace-high Straight Flush |
| `level` | integer \| null | the hand's level |
| `chips`, `mult` | number \| null | its base chips and mult |
| `scoring` | integer[] | the cards that would score |
| `not_allowed` | boolean | the boss blind forbids this hand |
| `hidden` | boolean | a face-down card is selected: the game shows `????` |

---

## GameSummaryView

An entry of `GET /games`.

| Field | Type |
|---|---|
| `id`, `version`, `settings`, `phase`, `ante`, `round`, `dollars`, `won` | as in GameView |
| `created_at`, `updated_at` | ISO 8601 date-time (UTC) |
| `best_hand` | Score | the run's best single hand |
| `counted` | boolean | the run counts for statistics and leaderboards |

A **Score** is a number, or `"inf"` / `"nan"` past the largest number (the
game writes "naneinf").

## Statistics

The fields are documented in the OpenAPI schema (`/docs`): `PlayerStats`
(`runs`, `high_scores`, `career`, `hands`, `jokers`, `consumables`,
`vouchers`, `decks`, `activity`), `Leaderboard` (`entries` of
`LeaderboardEntry`: `rank`, `player`, `you`, `value`, `deck`, `stake`, `won`,
`achieved_at`; and `you`), and `GlobalStats`.

## HistoryView

The response of `GET /games/{id}/history`.

| Field | Type | |
|---|---|---|
| `id`, `version` | | |
| `engine_version` | string | the BalatroEngine version the run was created with |
| `settings` | SettingsView | |
| `commands` | object[] | every accepted command, in the engine's format (`{"cmd": "play", "cards": [0, 2]}`, cards are positions in their area) |

---

## Catalog

The response of `GET /catalog`.

| Field | Type | Count | |
|---|---|---|---|
| `game_version`, `engine_version` | string | | |
| `decks` | CatalogItem[] | 15 | `b_red` ... `b_erratic` |
| `challenge_deck` | CatalogItem | 1 | `b_challenge`, the deck challenges are played with (it can't be chosen) |
| `stakes` | StakeItem[] | 8 | |
| `challenges` | ChallengeItem[] | 20 | |
| `jokers` | CatalogItem[] | 150 | |
| `tarots` | CatalogItem[] | 22 | |
| `planets` | CatalogItem[] | 12 | |
| `spectrals` | CatalogItem[] | 18 | |
| `vouchers` | CatalogItem[] | 32 | |
| `boosters` | CatalogItem[] | 32 | |
| `enhancements` | CatalogItem[] | 8 | `m_bonus` ... `m_lucky` |
| `editions` | CatalogItem[] | 4 | `e_foil`, `e_holo`, `e_polychrome`, `e_negative` |
| `seals` | CatalogItem[] | 4 | key `Gold`, `Red`, `Blue`, `Purple` |
| `stickers` | {name: Sprite} | 4 | `eternal`, `perishable`, `rental`, `debuff` |
| `tags` | TagItem[] | 24 | |
| `blinds` | BlindItem[] | 30 | |
| `poker_hands` | PokerHandItem[] | 12 | best first |
| `cards` | PlayingCardItem[] | 52 | |
| `atlases` | {name: AtlasView} | | the sprite sheets |

Lists are in the game's own order (the collection's order).

### CatalogItem

| Field | Type | |
|---|---|---|
| `key` | string | |
| `name` | string | |
| `set` | string | `Back`, `Joker`, `Tarot`, `Planet`, `Spectral`, `Voucher`, `Booster`, `Enhanced`, `Edition`, `Seal` |
| `sprite` | [Sprite](#sprite) \| null | |
| `cost` | number \| null | base price (before discounts and edition surcharges) |
| `rarity` | integer \| null | jokers: 1-4 |
| `config` | object \| null | the item's numbers, which its description fills in (`j_joker`: `{"mult": 4}`; `c_mercury`: `{"hand_type": "Pair"}`; boosters: `{"extra": 3, "choose": 1, "kind": "Arcana"}`, i.e. cards shown, cards chosen, pack kind) |
| `requires` | string[] \| null | vouchers: the voucher needed first |

### StakeItem

`level` (1-8), `key` (`stake_white`), `name` (`White Chip`), `sprite`.

### ChallengeItem

`id`, `name`, `deck` (deck key), `jokers`, `consumables` and `vouchers` the run
starts with (keys).

### BlindItem

| Field | Type | |
|---|---|---|
| `key`, `name` | string | |
| `boss` | boolean | |
| `showdown` | boolean | a final boss (ante 8, 16, ...) |
| `min_ante` | integer \| null | the earliest ante it can appear |
| `dollars` | number | reward |
| `mult` | number | the score needed, as a multiple of the ante's base |
| `colour` | string \| null | its colour, `#rrggbb` |
| `sprite` | Sprite \| null | |

### TagItem

`key`, `name`, `min_ante` (null: any ante), `sprite`.

### PokerHandItem

| Field | Type | |
|---|---|---|
| `name`, `display_name` | string | |
| `chips`, `mult` | number | at level 1 |
| `level_chips`, `level_mult` | number | added per level |
| `visible` | boolean | listed from the start |

### PlayingCardItem

`key` (`H_A`), `name` (`Ace of Hearts`), `rank`, `suit`, `sprite`.

### Sprite

| Field | Type | |
|---|---|---|
| `atlas` | string | the sprite sheet, a key of `Catalog.atlases` |
| `pos` | SpritePos | the cell: `{"x": column, "y": row}` |
| `soul_pos` | SpritePos \| null | a second layer drawn on top (legendary jokers, Hologram) |

### AtlasView

| Field | Type | |
|---|---|---|
| `file` | string | the image file in the game's `resources/textures/1x/` (and `2x/` at double size) |
| `px`, `py` | integer | the size of one cell at 1x |
| `frames` | integer \| null | animated sheets: frames per row |
