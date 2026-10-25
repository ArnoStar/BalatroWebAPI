"""What the use cases take and return: plain dataclasses.

They are the API contract: the HTTP layer serializes them as they are (and
documents them in the OpenAPI schema), so field names here are the JSON
names.  A view only holds what the player can see in the game: never the
deck order, the RNG state or what a face-down card is.

Card ids are the game's own card ids (``sort_id``): unique within a run and
stable for the card's whole life, so a front end can follow a card from the
deck to the hand, the play area and the discard pile.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from balatro_api.domain import Phase

CardKind = Literal["playing_card", "joker", "tarot", "planet", "spectral", "voucher", "booster"]
AreaName = Literal["deck", "hand", "play", "discard", "jokers", "consumables", "shop", "vouchers", "boosters", "pack"]
BlindSlot = Literal["Small", "Big", "Boss"]
Number = int | float
Score = int | float | str  # a score; "inf" or "nan" past the largest number (the game's "naneinf")


# ------------------------------------------------------------------ input
ActionType = Literal[
    "select_blind", "skip_blind", "reroll_boss",
    "play", "discard", "sort",
    "cash_out",
    "buy", "reroll", "end_shop",
    "use", "sell", "move",
    "pick", "skip_pack",
]


@dataclass(frozen=True, kw_only=True)
class PlayerAction:
    """One player action.  Cards are given by id; which fields are used
    depends on ``type`` (see the HTTP schema for each type)."""

    type: ActionType
    cards: tuple[int, ...] = ()  # play / discard
    card: int | None = None  # buy / use / sell / move / pick
    targets: tuple[int, ...] | None = None  # use / pick: hand cards the consumable acts on
    use: bool = False  # buy: buy a consumable and use it at once
    mode: Literal["rank", "suit"] = "rank"  # sort
    to: int | None = None  # move: the new position (0 = leftmost)


@dataclass(frozen=True, kw_only=True)
class NewGame:
    seed: str | None = None  # None: a random seed, as in an unseeded run
    deck: str = "b_red"
    stake: int = 1
    challenge: str | None = None
    game_speed: float = 1.0


# ------------------------------------------------------------------ cards
@dataclass(frozen=True, kw_only=True)
class Stickers:
    eternal: bool = False
    perishable: int | None = None  # rounds left before the joker is debuffed
    rental: bool = False


@dataclass(frozen=True, kw_only=True)
class CardView:
    """A card the player can see.  When ``face_down`` is true only ``id``,
    ``kind`` and ``selected`` are given, as the game hides the rest."""

    id: int
    kind: CardKind
    face_down: bool = False
    key: str | None = None  # the center: j_joker, c_fool, v_overstock_norm, p_arcana_normal_1, c_base, m_glass ...
    name: str | None = None
    rank: str | None = None  # playing cards: '2' .. '10', 'Jack', 'Queen', 'King', 'Ace'
    suit: str | None = None  # playing cards: 'Spades', 'Hearts', 'Clubs', 'Diamonds'
    card_key: str | None = None  # playing cards: 'H_A', 'S_T' ... (the front sprite)
    enhancement: str | None = None  # playing cards: m_bonus, m_glass ... (None: no enhancement)
    edition: Literal["foil", "holo", "polychrome", "negative"] | None = None
    seal: Literal["Gold", "Red", "Blue", "Purple"] | None = None
    stickers: Stickers | None = None
    rarity: int | None = None  # jokers: 1 common, 2 uncommon, 3 rare, 4 legendary
    debuffed: bool = False
    selected: bool = False
    forced_selection: bool = False  # Cerulean Bell: always selected
    cost: Number | None = None  # the price in the shop
    sell_value: Number | None = None
    bonus_chips: Number | None = None  # playing cards: chips added for good (Hiker)
    ability: dict[str, Any] | None = None  # jokers: the values their effect keeps (mult, x_mult, extra ...)


@dataclass(frozen=True, kw_only=True)
class DeckCardView:
    """A card still in the deck.  The deck's order is hidden, so these come
    sorted by suit and rank and carry no id."""

    key: str
    card_key: str
    rank: str
    suit: str
    enhancement: str | None = None
    edition: str | None = None
    seal: str | None = None


@dataclass(frozen=True, kw_only=True)
class DeckView:
    remaining: int
    total: int  # every playing card the run owns
    cards: list[DeckCardView]


# ------------------------------------------------------------------ run
@dataclass(frozen=True, kw_only=True)
class TagView:
    key: str
    name: str
    orbital_hand: str | None = None  # Orbital Tag: the poker hand it levels up


@dataclass(frozen=True, kw_only=True)
class BlindChoiceView:
    slot: BlindSlot
    key: str
    name: str
    state: Literal["Select", "Upcoming", "Current", "Defeated", "Skipped", "Hide"]
    chips: Number  # the score needed
    reward: Number  # dollars for beating it (0: no reward)
    skip_tag: TagView | None = None


@dataclass(frozen=True, kw_only=True)
class BlindSelectView:
    on_deck: BlindSlot
    choices: list[BlindChoiceView]
    boss_reroll_cost: Number | None = None  # None: the boss can't be rerolled


@dataclass(frozen=True, kw_only=True)
class BlindView:
    key: str
    name: str
    slot: BlindSlot | None
    chips: Number
    reward: Number
    boss: bool
    disabled: bool


@dataclass(frozen=True, kw_only=True)
class PokerHandView:
    name: str
    display_name: str
    level: int
    chips: Number
    mult: Number
    played: int
    visible: bool


@dataclass(frozen=True, kw_only=True)
class ShopView:
    jokers: list[CardView]
    vouchers: list[CardView]
    boosters: list[CardView]
    reroll_cost: Number
    free_rerolls: int


@dataclass(frozen=True, kw_only=True)
class PackView:
    kind: Literal["tarot", "planet", "spectral", "standard", "buffoon"]
    cards: list[CardView]
    choices_left: int


@dataclass(frozen=True, kw_only=True)
class RoundEvalRow:
    kind: Literal["blind", "hands", "discards", "joker", "tag", "interest"]
    dollars: Number
    key: str | None = None  # the joker or tag that pays


@dataclass(frozen=True, kw_only=True)
class RoundEvalView:
    rows: list[RoundEvalRow]
    total: Number


@dataclass(frozen=True, kw_only=True)
class HandScore:
    hand: str
    chips: Number
    mult: Number
    score: Number


@dataclass(frozen=True, kw_only=True)
class RoundTargets:
    """This round's targets of The Idol, Mail-In Rebate, Ancient Joker and
    Castle (they change every round), and the most played hand (The Ox)."""

    idol_rank: str | None = None
    idol_suit: str | None = None
    mail_rank: str | None = None
    ancient_suit: str | None = None
    castle_suit: str | None = None
    most_played_hand: str | None = None


@dataclass(frozen=True, kw_only=True)
class RunInfo:
    """Values that card descriptions read (what the game's tooltips show)."""

    probability_normal: Number  # 1, doubled by each Oops! All 6s
    last_tarot_planet: str | None  # what The Fool would create
    interest_amount: Number
    interest_cap: Number
    discount_percent: Number
    bankrupt_at: Number  # how far into debt the run may go (Credit Card)
    skips: int
    hands_played: int
    unused_discards: int
    round_targets: RoundTargets


@dataclass(frozen=True, kw_only=True)
class LegalAction:
    """One thing the player can do now.  Send it back (with the cards it
    leaves open) as a :class:`PlayerAction`."""

    type: ActionType
    card: int | None = None
    area: AreaName | None = None  # buy / sell / move: where the card is
    use: bool | None = None  # buy: buy and use at once
    mode: Literal["rank", "suit"] | None = None
    min_cards: int | None = None  # play / discard
    max_cards: int | None = None
    min_targets: int | None = None  # use / pick: hand cards to select
    max_targets: int | None = None
    cost: Number | None = None  # buy / reroll / reroll_boss
    value: Number | None = None  # sell


@dataclass(frozen=True, kw_only=True)
class SettingsView:
    seed: str
    deck: str
    stake: int
    challenge: str | None
    game_speed: float
    seeded: bool = False  # the player chose the seed: the run doesn't count for statistics


@dataclass(frozen=True, kw_only=True)
class GameView:
    id: str
    version: int  # send it back as expected_version to act on exactly this state
    settings: SettingsView
    phase: Phase
    state: str  # the game's own state name (SELECTING_HAND, TAROT_PACK ...)
    won: bool  # the run beat ante 8 (it may go on, in endless mode)
    ante: int
    round: int
    dollars: Number
    hands_left: int
    discards_left: int
    hand_size: int
    joker_slots: int
    consumable_slots: int
    round_score: Number
    blind: BlindView | None
    blind_select: BlindSelectView | None
    hand: list[CardView]
    jokers: list[CardView]
    consumables: list[CardView]
    deck: DeckView
    discard_count: int
    shop: ShopView | None
    pack: PackView | None
    round_eval: RoundEvalView | None
    tags: list[TagView]
    vouchers: list[str]
    poker_hands: list[PokerHandView]
    last_hand: HandScore | None
    info: RunInfo
    actions: list[LegalAction]


@dataclass(frozen=True, kw_only=True)
class GameSummaryView:
    id: str
    version: int
    settings: SettingsView
    phase: Phase
    ante: int
    round: int
    dollars: Number
    won: bool
    created_at: datetime
    updated_at: datetime
    best_hand: Score = 0  # the run's best single hand
    counted: bool = True  # the run counts for statistics and leaderboards (not seeded, no challenge, no debug)


@dataclass(frozen=True, kw_only=True)
class HandPreview:
    """What the game shows while these cards are selected."""

    selected: list[int]  # card ids, including a forced card
    hand: str | None  # the poker hand (None: nothing selected)
    display_name: str | None = None  # 'Royal Flush' for an ace-high straight flush
    level: int | None = None
    chips: Number | None = None
    mult: Number | None = None
    scoring: list[int] = field(default_factory=list)  # the cards that would score
    not_allowed: bool = False  # the boss blind forbids this hand
    hidden: bool = False  # a face-down card is selected: the game shows '????'


@dataclass(frozen=True, kw_only=True)
class HistoryView:
    id: str
    version: int
    engine_version: str
    settings: SettingsView
    commands: list[dict[str, Any]]  # in the engine's format (indices into the areas)


# ------------------------------------------------------------------ feedback
@dataclass(frozen=True, kw_only=True)
class HandPanelEvent:
    """The scoring panel changes (only the values that change are given)."""

    type: Literal["hand"] = "hand"
    t: float
    hand: str | None = None
    level: int | str | None = None
    chips: Number | str | None = None
    mult: Number | str | None = None
    hand_score: Number | None = None


@dataclass(frozen=True, kw_only=True)
class CardTextEvent:
    """A pop-up over a card: a scoring effect, a retrigger, a message."""

    type: Literal["card_text"] = "card_text"
    t: float
    card: int | None
    effect: Literal["chips", "mult", "x_mult", "dollars", "again", "debuffed", "swap", "message"]
    amount: Number | None = None
    message: str | None = None
    held: bool = False  # a held-in-hand effect
    edition: bool = False  # from the card's edition


@dataclass(frozen=True, kw_only=True)
class HandScoredEvent:
    type: Literal["hand_scored"] = "hand_scored"
    t: float
    hand: str
    chips: Number
    mult: Number
    score: Number
    round_score: Number


@dataclass(frozen=True, kw_only=True)
class RoundScoreEvent:
    type: Literal["round_score"] = "round_score"
    t: float
    chips: Number


@dataclass(frozen=True, kw_only=True)
class DollarsEvent:
    type: Literal["dollars"] = "dollars"
    t: float
    amount: Number
    total: Number


@dataclass(frozen=True, kw_only=True)
class StatusTextEvent:
    type: Literal["status_text"] = "status_text"
    t: float
    text: str


@dataclass(frozen=True, kw_only=True)
class CardMovedEvent:
    type: Literal["card_moved"] = "card_moved"
    t: float
    card: int
    to: AreaName


@dataclass(frozen=True, kw_only=True)
class CardFlippedEvent:
    type: Literal["card_flipped"] = "card_flipped"
    t: float
    card: int
    face_down: bool


@dataclass(frozen=True, kw_only=True)
class CardRemovedEvent:
    type: Literal["card_removed"] = "card_removed"
    t: float
    card: int
    area: AreaName


FeedbackEvent = (HandPanelEvent | CardTextEvent | HandScoredEvent | RoundScoreEvent | DollarsEvent | StatusTextEvent
                 | CardMovedEvent | CardFlippedEvent | CardRemovedEvent)


@dataclass(frozen=True, kw_only=True)
class ActionResult:
    """The game after the action, and what the player saw happen, in order.
    ``t`` is the time in seconds (at the run's game speed, 60 fps) at which
    the game shows each event, so a front end can replay the animation."""

    game: GameView
    events: list[FeedbackEvent]


# ------------------------------------------------------------------ catalog
@dataclass(frozen=True, kw_only=True)
class SpritePos:
    x: int
    y: int


@dataclass(frozen=True, kw_only=True)
class Sprite:
    atlas: str
    pos: SpritePos
    soul_pos: SpritePos | None = None  # a second layer (legendary jokers, Hologram)


@dataclass(frozen=True, kw_only=True)
class AtlasView:
    file: str  # in the game's resources/textures/1x or 2x
    px: int  # cell size at 1x
    py: int
    frames: int | None = None  # animated sheets


@dataclass(frozen=True, kw_only=True)
class CatalogItem:
    key: str
    name: str
    set: str
    sprite: Sprite | None = None
    cost: Number | None = None
    rarity: int | None = None  # jokers
    config: dict[str, Any] | None = None  # the item's numbers (what its description fills in)
    requires: list[str] | None = None  # vouchers: the voucher needed first


@dataclass(frozen=True, kw_only=True)
class StakeItem:
    level: int
    key: str
    name: str
    sprite: Sprite | None = None


@dataclass(frozen=True, kw_only=True)
class BlindItem:
    key: str
    name: str
    boss: bool
    showdown: bool  # a final (ante 8, 16 ...) boss
    min_ante: int | None
    dollars: Number
    mult: Number
    colour: str | None = None
    sprite: Sprite | None = None


@dataclass(frozen=True, kw_only=True)
class TagItem:
    key: str
    name: str
    min_ante: int | None = None
    sprite: Sprite | None = None


@dataclass(frozen=True, kw_only=True)
class ChallengeItem:
    id: str
    name: str
    deck: str
    jokers: list[str]
    consumables: list[str]
    vouchers: list[str]


@dataclass(frozen=True, kw_only=True)
class PlayingCardItem:
    key: str
    name: str
    rank: str
    suit: str
    sprite: Sprite | None = None


@dataclass(frozen=True, kw_only=True)
class PokerHandItem:
    name: str
    display_name: str
    chips: Number
    mult: Number
    level_chips: Number  # added per level
    level_mult: Number
    visible: bool  # visible from the start (the others appear once played)


@dataclass(frozen=True, kw_only=True)
class Catalog:
    """Everything static a front end needs: names, prices, sprites."""

    game_version: str
    engine_version: str
    decks: list[CatalogItem]
    challenge_deck: CatalogItem  # b_challenge: the deck most challenges are played with (not choosable)
    stakes: list[StakeItem]
    challenges: list[ChallengeItem]
    jokers: list[CatalogItem]
    tarots: list[CatalogItem]
    planets: list[CatalogItem]
    spectrals: list[CatalogItem]
    vouchers: list[CatalogItem]
    boosters: list[CatalogItem]
    enhancements: list[CatalogItem]
    editions: list[CatalogItem]
    seals: list[CatalogItem]
    stickers: dict[str, Sprite]
    tags: list[TagItem]
    blinds: list[BlindItem]
    poker_hands: list[PokerHandItem]
    cards: list[PlayingCardItem]
    atlases: dict[str, AtlasView]


@dataclass(frozen=True, kw_only=True)
class Player:
    """Who is calling: the account id (``sub``) and display name (``name``)
    from the identity service's access token, or the anonymous player when the
    server runs without sign-in."""

    id: str
    name: str | None = None


# ------------------------------------------------------------------ statistics
# As in the game, statistics only count runs whose seed the player didn't
# choose and that aren't challenges (and here, runs without debug commands).

@dataclass(frozen=True, kw_only=True)
class RunCounts:
    total: int  # every run, counted or not
    counted: int  # the runs that count for statistics
    won: int  # counted runs that beat ante 8
    lost: int  # counted runs that ended before winning
    in_progress: int  # counted runs neither won nor over


@dataclass(frozen=True, kw_only=True)
class UsageCount:
    key: str  # a poker hand name, or a consumable / voucher key (see GET /catalog)
    count: int


@dataclass(frozen=True, kw_only=True)
class HighScores:
    """The game's profile high scores ("Best Hand", "Highest Round" ...)."""

    best_hand: Score
    highest_round: int
    highest_ante: int
    most_money: Number
    boss_streak: int  # most boss blinds beaten in a row
    best_win_streak: int  # most runs won in a row (in the order they were last played)
    current_win_streak: int
    most_played_hand: UsageCount | None


@dataclass(frozen=True, kw_only=True)
class CareerStats:
    """The game's career stats, added up over the counted runs."""

    wins: int
    losses: int
    rounds: int  # blinds started
    hands_played: int
    cards_played: int
    face_cards_played: int
    cards_discarded: int
    dollars_earned: Number
    shop_dollars_spent: Number
    shop_rerolls: int
    jokers_sold: int
    cards_sold: int
    tarots_bought: int
    planets_bought: int
    playing_cards_bought: int
    vouchers_bought: int
    tarot_readings_used: int  # Arcana packs opened to the end
    planetariums_used: int  # Celestial packs opened to the end


@dataclass(frozen=True, kw_only=True)
class JokerStats:
    key: str
    runs: int  # runs in which it was held at the end of a won round
    rounds: int  # won rounds it was held in (the game's joker usage)
    wins: int  # copies held when a run was won
    losses: int  # copies held when a run was lost
    best_stake_won: int | None  # the highest stake won with it (the game's joker stickers)


@dataclass(frozen=True, kw_only=True)
class StakeRecord:
    stake: int
    runs: int
    wins: int
    losses: int


@dataclass(frozen=True, kw_only=True)
class DeckStats:
    deck: str
    runs: int
    wins: int
    losses: int
    best_stake_won: int | None  # the game's deck stickers
    stakes: list[StakeRecord]  # only the stakes played


@dataclass(frozen=True, kw_only=True)
class DayActivity:
    date: str  # YYYY-MM-DD (UTC), the day runs were started
    runs: int
    wins: int  # runs started that day and won


@dataclass(frozen=True, kw_only=True)
class PlayerStats:
    """A player's profile statistics, as the game's Profile > Stats screens
    show them, from their counted runs."""

    runs: RunCounts
    high_scores: HighScores
    career: CareerStats
    hands: list[UsageCount]  # poker hands by times played (most first)
    jokers: list[JokerStats]  # by rounds held (most first)
    consumables: list[UsageCount]  # by times used
    vouchers: list[UsageCount]  # by times redeemed
    decks: list[DeckStats]  # by runs played
    activity: list[DayActivity]  # the last 30 days, oldest first (days without runs included)


LeaderboardName = Literal["best_hand", "highest_ante", "highest_round", "most_money", "boss_streak", "wins"]


@dataclass(frozen=True, kw_only=True)
class LeaderboardEntry:
    rank: int  # 1 = the best; tied values share a rank
    player: str | None  # the player's display name (None: no name)
    you: bool  # this is the caller's entry
    value: Score
    deck: str | None  # where the value was reached (None for "wins")
    stake: int | None
    won: bool | None  # that run beat ante 8 (None for "wins")
    achieved_at: datetime  # when that run was last played (for "wins": the latest win)


@dataclass(frozen=True, kw_only=True)
class Leaderboard:
    """The best counted run of each player (or, for "wins", each player's
    number of won runs), optionally on one deck and/or stake."""

    board: LeaderboardName
    deck: str | None
    stake: int | None
    players: int  # players on the board
    entries: list[LeaderboardEntry]  # the top ones
    you: LeaderboardEntry | None  # the caller's entry, even outside the top (None: not on the board)


@dataclass(frozen=True, kw_only=True)
class DeckPopularity:
    deck: str
    runs: int
    wins: int


@dataclass(frozen=True, kw_only=True)
class StakePopularity:
    stake: int
    runs: int
    wins: int


@dataclass(frozen=True, kw_only=True)
class JokerPopularity:
    key: str
    runs: int  # runs that held it at the end of a won round
    win_runs: int  # won runs that held it when they were won


@dataclass(frozen=True, kw_only=True)
class GlobalStats:
    """Everyone's counted runs together."""

    players: int
    runs: int
    won: int
    lost: int
    hands_played: int
    cards_played: int
    dollars_earned: Number
    best_hand: Score
    highest_ante: int
    decks: list[DeckPopularity]  # by runs
    stakes: list[StakePopularity]  # by stake
    jokers: list[JokerPopularity]  # the 20 most held
    hands: list[UsageCount]  # poker hands by times played
