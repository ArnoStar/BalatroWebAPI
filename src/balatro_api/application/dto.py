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
