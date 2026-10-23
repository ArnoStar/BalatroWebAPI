# Animations: replaying what happened

An action can set off a long sequence on screen: cards fly to the play area,
each scoring card shows `+9`, a joker shows `+4 Mult`, the score counts up,
money changes, cards go to the discard pile and new ones are drawn. The API
plays all of it at once and returns the result. It also returns `events`: the
same sequence as data, in order, each event stamped with the time at which
the game shows it.

The fields of every event type are listed in
[Data models](models.md#events). This page explains how to use them.

## The timeline

`t` is in seconds from the moment the action was taken. It is real time at
60 frames per second, at the run's `game_speed`. That is the pace a player of
the original game sees, including the speed-up the game applies during long
scoring sequences. To reproduce the game's pacing, schedule each event at `t`:

```js
const start = performance.now();
for (const e of result.events) {
  await sleepUntil(start + e.t * 1000 / playbackSpeed);
  apply(e);              // move a card, show a pop-up, update the panel...
}
render(result.game);     // the final state is authoritative
```

Events with the same `t` happen in the same frame, in list order. A front end
can also ignore `t`, play the events at its own pace, compress long
sequences, or skip them on a "fast" setting. The order is what matters. The
returned `game` is always the true final state: after the animation, render
it and discard whatever the animation built up.

## A played hand, event by event

Playing A♥ K♥ Q♦ 9♠ 9♣ (ids 35, 37, 25, 47, 8) on the TESTSEED Small Blind
returns these events (unchanged `false`/`null` fields left out):

```
t=0.017  hand         hand="" level=""                        selection reset (see below)
t=0.017  hand         hand="High Card" level=1 chips=5 mult=1 ... the selection, card by card
t=0.017  hand         hand="Pair" level=1 chips=10 mult=2
t=0.550  card_moved   card=35 to=play                         the cards go to the play area
  ...    card_moved   cards 37, 25, 47, then 8 (t=1.017) to=play
t=1.150  hand         hand="Pair" level=1 chips=10 mult=2     the panel shows the hand played
t=2.183  hand         chips=19                                the first 9 scores: chips 10 -> 19
t=2.200  card_text    card=47 effect=chips amount=9           "+9" over the 9 of Spades
t=2.967  hand         chips=28
t=2.983  card_text    card=8 effect=chips amount=9            "+9" over the 9 of Clubs
t=4.700  hand_scored  hand=Pair chips=28 mult=2 score=56 round_score=56
t=4.700  hand         hand="" level="" hand_score=56          the panel shows the total, then clears
t=6.417  card_moved   card=35 to=discard                      played cards to the discard pile...
t=6.417  card_flipped card=35 face_down=true                  ...face down
  ...                 (the same for 37, 25, 47 and 8)
t=7.350  card_flipped card=13 face_down=false                 new cards drawn, turned face up
t=7.350  card_moved   card=13 to=hand
  ...                 (cards 7, 32, 48, 12)
```

With a Joker, a `card_text` with `effect=mult amount=4` appears over the
joker after the cards score. The `hand_scored` event then shows `mult=6` and
`score=168`.

## What each event means on screen

| Event | Suggested rendering |
|---|---|
| `card_moved` | Move card `card` to area `to` (append at the right). The final order is in `game`. |
| `card_flipped` | Turn the card over. A card flipping twice in a row (`true`, then `false`) is being changed by a consumable: The Magician, Strength, Death... |
| `card_removed` | The card leaves: sold, used, destroyed (Glass shattering, Ceremonial Dagger, eaten Gros Michel...), or a shop card disappearing when the shop closes. |
| `hand` | Update the scoring panel with the fields present. `hand` is the hand name, `chips` and `mult` the running values, `hand_score` the hand's total. `""` clears a field, `"?"` hides it. |
| `card_text` | A pop-up over card `card`: `+N` for `chips`, `+N Mult` for `mult`, `XN Mult` for `x_mult`, `$N` for `dollars`, `Again!` for `again`, `Debuffed!`... The card can be a playing card, a joker or a consumable (Observatory). |
| `hand_scored` | The hand's result: chips × mult = score. `round_score` is the new round total, which the game counts up to. |
| `round_score` | The round score is set: reset to 0 at cash out. |
| `dollars` | Money changes by `amount` (`+$3`, `-$5`) to `total`. |
| `status_text` | Text over the play area, for example `Not Allowed!` when the boss blind forbids the hand. |

## Things to know

- **The selection comes first.** A `play`, `discard` or targeted `use` starts
  by selecting the cards, one at a time, as the player would. The panel
  updates as each card is selected: the `hand` events at the very start. A
  front end that already shows its own selection can ignore the events before
  the first `card_moved`.
- **Card ids in events are the same ids as in `GameView`.** A card created
  during the action (a Tarot from 8 Ball, a card from DNA or Certificate)
  first appears in a `card_moved` event and then in the new `game`.
- **Face-down cards.** Events never reveal what a face-down card is; they only
  say that it moved or turned over.
- **Every action has events**, not only `play`. `cash_out` has `dollars` and `round_score`,
  buying has a `dollars` and a `card_moved`, `select_blind` deals the hand,
  `end_shop` removes the shop cards.
