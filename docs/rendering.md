# Rendering

How to draw the game with the data the API gives: names, card faces from the
game's sprite sheets, and what to show of hidden cards.

## Names

Every view carries display names (`CardView.name`, `BlindView.name`,
`TagView.name`, `PokerHandView.display_name`). Everything else is a key:
`j_joker`, `bl_hook`, `tag_charm`. `GET /catalog` maps every key to its name,
price, numbers and sprite. Fetch the catalog once and index it by key.

The API gives no description text. For tooltips, write your own descriptions
and fill them in with:

- the item's `config` in the catalog (Joker: `{"mult": 4}`);
- the card's live values in `CardView.ability` (Ride the Bus's mult so far,
  Ice Cream's chips left);
- the run's values in `GameView.info`: the "1 in N" chances
  (`probability_normal`), the round's targets of The Idol, Mail-In Rebate,
  Ancient Joker and Castle (`round_targets`), what The Fool would create
  (`last_tarot_planet`).

## Sprites

The API does not serve the game's images. A front end loads them from a copy
of the game. In the game's files they are in `resources/textures/1x/` (and
`2x/` at double resolution).

`GET /catalog` gives:

- **`atlases`**: each sprite sheet's `file` and the size of one cell at 1x
  (`px` × `py`). Animated sheets also give `frames`.
- **A `sprite` for every item**: its `atlas` and its cell `pos`
  (`x` column, `y` row). Legendary jokers and Hologram also have `soul_pos`,
  a second layer drawn on top.

The source rectangle of a sprite is:

```
x = pos.x * px, y = pos.y * py, width = px, height = py      (times 2 at 2x)
```

| Item | Atlas | Cell size |
|---|---|---|
| Jokers | `Joker` (`Jokers.png`) | 71 × 95 |
| Tarot, Planet and Spectral cards | `Tarot`, `Planet`, `Spectral` (all `Tarots.png`) | 71 × 95 |
| Vouchers | `Voucher` (`Vouchers.png`) | 71 × 95 |
| Booster packs | `Booster` (`boosters.png`) | 71 × 95 |
| Card backs (decks), enhancements, seals | `centers` (`Enhancers.png`) | 71 × 95 |
| Playing card fronts | `cards_1` (`8BitDeck.png`); `cards_2` is the high-contrast deck | 71 × 95 |
| Stickers (Eternal, Perishable, Rental) | `stickers` (`stickers.png`) | 71 × 95 |
| Tags | `tags` (`tags.png`) | 34 × 34 |
| Blinds | `blind_chips` (`BlindChips.png`, animated: 21 frames per row) | 34 × 34 |
| Stake chips | `chips` (`chips.png`) | 29 × 29 |

### Drawing a playing card

A playing card is drawn in layers, like the game does:

1. **The base:** the sprite of its `key`. That is the enhancement (Bonus,
   Glass...) or, for `c_base`, the plain card. A Stone card (`m_stone`) is
   drawn with no front.
2. **The front:** the `cards` entry of its `card_key` in the catalog (atlas
   `cards_1`).
3. **The seal**, if any: `seals[seal].sprite`.
4. **The edition** (foil, holographic, polychrome, negative) is a shader in the
   game. Draw it as an effect of your own.
5. **Debuffed:** `stickers.debuff` drawn over the card.

### Drawing a joker or a consumable

Draw the item's `sprite`, then its `soul_pos` layer if it has one (legendary
jokers, Hologram). Add sticker sprites from `stickers` for
`CardView.stickers`, and the edition effect.

### Face-down cards

A card with `face_down: true` carries only its `id`. Draw the back of the
run's deck: the sprite of `settings.deck` in `decks` (or `challenge_deck`,
for `b_challenge`). The deck pile and the
discard pile are always face down.

## What is hidden

The API follows the game: a view only holds what the player can see.

- The deck's order is never given. `deck.cards` lists what is left, sorted and
  without ids, as the game's deck view does.
- Face-down cards (The House, The Wheel, The Mark, The Fish, Amber Acorn) show
  nothing but their id. The hand preview hides the hand when one is selected.
- The shop's next cards and the contents of an unopened pack are not given.
  Neither is anything random.
