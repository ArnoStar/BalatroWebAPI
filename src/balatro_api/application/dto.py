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
    "continue",
    "creative",  # (a legal action only: a run with creative mode; POST /games/{id}/creative)
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
class ModChoice:
    """A mod to play a run with: a package (the mod's JSON, e.g. imported from a file), or a
    published mod by ``id`` (its latest version, or ``version``), or a package the server has by ``hash``."""

    package: dict[str, Any] | None = None
    id: str | None = None
    version: str | None = None
    hash: str | None = None


@dataclass(frozen=True, kw_only=True)
class NewGame:
    seed: str | None = None  # None: a random seed, as in an unseeded run
    deck: str = "b_red"
    stake: int = 1
    challenge: str | None = None
    game_speed: float = 1.0
    mods: tuple[ModChoice, ...] = ()  # content mods (the run then doesn't count, nor unlock anything)


@dataclass(frozen=True, kw_only=True)
class CreativeCommand:
    """A creative mode change (a run with a creative mod): see BalatroEngine's docs/mods.md.
    ``card``: the card ``edit`` and ``remove`` act on, by id (a joker, a consumable or a hand card)."""

    op: Literal["set", "level", "add", "add_card", "edit", "remove", "boss", "win"]
    what: str | None = None
    value: Number | None = None
    hand: str | None = None
    key: str | None = None
    card: int | None = None
    edition: str | None = None
    seal: str | None = None
    enhancement: str | None = None
    rank: str | None = None
    suit: str | None = None
    to: Literal["hand", "deck"] | None = None
    eternal: bool | None = None
    perishable: bool | None = None
    rental: bool | None = None


@dataclass(frozen=True, kw_only=True)
class ImportedRun:
    """A run to rebuild from its settings and commands (a run's history, e.g.
    from a bug report)."""

    seed: str
    deck: str = "b_red"
    stake: int = 1
    challenge: str | None = None
    game_speed: float = 1.0
    commands: tuple[dict[str, Any], ...] = ()
    seeded: bool = True  # the player chose the seed (a history before progress was kept: true)
    start_profile: dict[str, Any] | None = None  # the progress the run started from (HistoryView.start_profile)
    mods: tuple[dict[str, Any], ...] = ()  # the history's settings.mods (ModRefView)
    mod_packages: dict[str, dict[str, Any]] | None = None  # the history's packages, by hash
    mode: str | None = None  # a multiplayer run's rules (pvp, coop), which its commands were played by
    mode_rules: int | None = None  # the version of the mode's rules (the history's settings.mode_rules)


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
    pinned: bool = False  # a challenge's pinned joker: it stays leftmost (CardArea:align_cards)
    cost: Number | None = None  # the price in the shop
    sell_value: Number | None = None
    bonus_chips: Number | None = None  # playing cards: chips added for good (Hiker)
    ability: dict[str, Any] | None = None  # jokers: the values their effect keeps (mult, x_mult, extra ...)
    owner: int | None = None  # coop: the seat of the player whose joker it is (they alone sell and move it)


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
    # Tarots, Planets, Spectrals used this run, by kind (Fortune Teller) and by card (Satellite)
    consumable_usage_total: dict[str, int] = field(default_factory=dict)
    consumable_usage: dict[str, int] = field(default_factory=dict)
    ecto_minus: int = 1  # hand size the next Ectoplasm takes


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
class ModRefView:
    """A content mod a run is played with: its package is ``GET /mods/packages/{hash}``."""

    id: str
    version: str
    hash: str
    name: str = ""
    creative: bool = False  # creative mode: POST /games/{id}/creative


@dataclass(frozen=True, kw_only=True)
class SettingsView:
    seed: str
    deck: str
    stake: int
    challenge: str | None
    game_speed: float
    seeded: bool = False  # the player chose the seed: the run doesn't count for statistics
    mode: str | None = None  # a multiplayer run's mode ("pvp"), with its rules; None: the game's own rules
    # the version of the mode's rules (coop: 1, a deck each and slow blinds; 2, one deck and steep blinds); None:
    # the mode's first (send it back with the history when importing a run)
    mode_rules: int | None = None
    mods: list[ModRefView] = field(default_factory=list)  # content mods: the run doesn't count


@dataclass(frozen=True, kw_only=True)
class CoopSeatView:
    deck: int  # cards left in their deck (one deck for both: the deck's)
    hand: int  # cards in their hand (the turn's is ``hand``; one deck for both: the hand's)
    # the player's numbers this run: hands played, the chips they scored, their best hand, discards
    hands: int = 0
    chips: Score = 0
    best_hand: Score = 0
    best_hand_name: str | None = None
    discards: int = 0


@dataclass(frozen=True, kw_only=True)
class CoopView:
    """A coop run: two players in turns, each with their own deck; jokers, hands and discards shared."""

    seat: int | None  # yours (None: not one of the players)
    turn: int  # whose turn it is: they play, discard and choose the blind (the shown hand is theirs)
    your_turn: bool
    joker_slots: list[int]  # each seat's (``jokers``' ``owner``)
    shop_votes: list[int]  # the seats that asked to leave the shop (it is left once both have)
    pack_seat: int | None  # who opened the pack on screen (they pick from it, and select the hand's cards for it)
    seats: list[CoopSeatView]
    shared_deck: bool = False  # one deck and hand for both players (else each has their own: mode_rules 1)


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
    # the cards the shop offers besides vouchers and packs: 2, and 1 more with each of Overstock and
    # Overstock Plus (the Zodiac Deck starts with Overstock)
    shop_slots: int = 2
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
    coop: CoopView | None = None  # a coop run: whose turn it is, the jokers' halves (``actions`` are your seat's)


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
    # the player's progress when the run started, which decides the pools (null: a run from before progress
    # was kept, played fully unlocked); a rebuild passes it back
    start_profile: dict[str, Any] | None = None
    # the logic of the run's mods (settings.mods), by hash: a rebuild passes them back
    mod_packages: dict[str, dict[str, Any]] = field(default_factory=dict)


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
    # turned face up: how the card looks (a tarot or spectral may just have changed it, and the
    # card can end the action in the deck, which the view doesn't list)
    view: CardView | None = None


@dataclass(frozen=True, kw_only=True)
class CardJuicedEvent:
    type: Literal["card_juiced"] = "card_juiced"
    t: float
    # a card wiggles: the joker behind a scored or held card's effect, the Uncommon Joker that
    # Baseball Card multiplies, a card that Midas Mask turns Gold or that Vampire drains
    card: int
    scale: float | None = 0.7  # Card:juice_up's arguments; null: its defaults
    rot: float | None = None


@dataclass(frozen=True, kw_only=True)
class CardChangedEvent:
    type: Literal["card_changed"] = "card_changed"
    t: float
    card: int
    # the card shines with its new edition or seal (Aura, Hex, Deja Vu...), or shows its new enhancement while a
    # hand is scored (Midas Mask's Gold Cards, Vampire's taken ones)
    change: Literal["edition", "seal", "enhancement"]
    view: CardView | None = None  # how it looks now


@dataclass(frozen=True, kw_only=True)
class CardUnlockedEvent:
    type: Literal["card_unlocked"] = "card_unlocked"
    t: float
    key: str  # a joker, voucher or deck the player has just unlocked (the game's "Unlocked!" notification)
    set: str  # Joker, Voucher or Back


@dataclass(frozen=True, kw_only=True)
class AttentionTextEvent:
    type: Literal["attention_text"] = "attention_text"
    t: float
    card: int  # the big text is over this card
    key: str  # the text's localization key (k_nope_ex: The Wheel of Fortune missed)


@dataclass(frozen=True, kw_only=True)
class CardRemovedEvent:
    type: Literal["card_removed"] = "card_removed"
    t: float
    card: int
    area: AreaName


@dataclass(frozen=True, kw_only=True)
class TurnEvent:
    type: Literal["turn"] = "turn"
    t: float
    seat: int  # coop: the turn passes to this seat (their hand comes up)


@dataclass(frozen=True, kw_only=True)
class ShopVoteEvent:
    type: Literal["shop_vote"] = "shop_vote"
    t: float
    seats: list[int]  # coop: who has asked to leave the shop


FeedbackEvent = (HandPanelEvent | CardTextEvent | HandScoredEvent | RoundScoreEvent | DollarsEvent | StatusTextEvent
                 | CardMovedEvent | CardFlippedEvent | CardRemovedEvent | CardJuicedEvent | CardChangedEvent
                 | AttentionTextEvent | CardUnlockedEvent | TurnEvent | ShopVoteEvent)


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
    roles: frozenset[str] = frozenset()  # the token's ``roles`` (application/permissions.py)


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
    player_id: str | None = None  # the player's profile (GET /players/{id})
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


# ------------------------------------------------------------------ progress and players
@dataclass(frozen=True, kw_only=True)
class ProgressView:
    """The player's progress, as the game's profile keeps it: what the run setup, the shop and
    the collection show as unlocked and discovered."""

    all_unlocked: bool  # the player has switched "unlock everything" on (testers): new runs are fully unlocked
    can_unlock_all: bool  # the player's roles allow that switch
    unlocked: list[str]  # the jokers, decks and vouchers unlocked beyond those a new save has
    discovered: list[str]  # centers, tags and blinds discovered (the collection shows the others as "?")
    challenges_completed: list[str]
    challenges_unlocked: int  # the first N challenges (catalog order) are open
    deck_stakes: dict[str, int]  # deck key -> the highest stake won with it
    max_stakes: dict[str, int]  # deck key -> the highest stake a new run can have with it
    # the profile's career stats (c_face_cards_played, c_jokers_sold ...) and how many times each voucher
    # was redeemed: a locked card's unlock condition shows how far the player is (e.g. "(287)")
    career_stats: dict[str, Number] = field(default_factory=dict)
    voucher_usage: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class CollectionCount:
    found: int
    total: int


@dataclass(frozen=True, kw_only=True)
class CollectionView:
    """How much of the game a player has discovered (the collection's counts)."""

    jokers: CollectionCount
    tarots: CollectionCount
    planets: CollectionCount
    spectrals: CollectionCount
    vouchers: CollectionCount
    boosters: CollectionCount
    editions: CollectionCount
    blinds: CollectionCount
    tags: CollectionCount
    decks: CollectionCount  # unlocked
    challenges: CollectionCount  # completed
    deck_stakes: dict[str, int]  # deck key -> the highest stake won with it


@dataclass(frozen=True, kw_only=True)
class PlayerSettings:
    """What a player changes on their own account here."""

    private: bool | None = None  # only the name shows on the profile; the runs can't be watched
    all_unlocked: bool | None = None  # testers: new runs fully unlocked (the real progress stays as it is)


@dataclass(frozen=True, kw_only=True)
class MeView:
    id: str
    name: str | None
    private: bool
    progress: ProgressView


@dataclass(frozen=True, kw_only=True)
class PlayerProfileView:
    """A player's public profile. A private one (not the caller's) has only the name."""

    id: str
    name: str | None
    you: bool
    private: bool
    stats: PlayerStats | None = None
    collection: CollectionView | None = None
    runs: list[GameSummaryView] = field(default_factory=list)  # recent runs (others': finished ones only)
    multiplayer: MultiplayerStats | None = None  # their PvP and coop matches
    matches: list[MatchHistoryEntry] = field(default_factory=list)  # their latest matches


@dataclass(frozen=True, kw_only=True)
class ReplayStep:
    version: int  # the run's version before this step
    # a player action (as POST /games/{id}/actions takes it), or {"type": "debug", "command": ...}
    action: dict[str, Any]
    # the player's pointer before the action, as the game sent it with the action (its own format;
    # None: not sent, as by runs played before it was kept)
    pointer: dict[str, Any] | None = None


@dataclass(frozen=True, kw_only=True)
class WatchView:
    """A copy of a run to watch it again: play ``steps`` on ``game`` (a new run of the caller's,
    not listed and not counted), each with its usual animations."""

    source: str  # the watched run
    owner_name: str | None
    game: GameView
    steps: list[ReplayStep]


# ------------------------------------------------------------------ multiplayer
MatchMode = Literal["pvp", "coop"]
MatchStatusName = Literal["lobby", "playing", "finished"]
BlindChoice = Literal["select", "skip"]
EmoteName = Literal["gg", "nice", "wow", "oops", "hurry", "thanks", "good_luck", "well_played"]


@dataclass(frozen=True, kw_only=True)
class NewMatch:
    mode: MatchMode = "pvp"
    deck: str = "b_red"
    stake: int = 1
    seed: str | None = None  # None: a random seed (the same for both players)
    timer: int = 120  # seconds a player has once the other one waits for them
    game_speed: float = 1.0  # the creator's game speed setting (their run's)


@dataclass(frozen=True, kw_only=True)
class MatchSettingsChange:
    deck: str = "b_red"
    stake: int = 1
    seed: str | None = None
    timer: int = 120


@dataclass(frozen=True, kw_only=True)
class MatchSettingsView:
    deck: str
    stake: int
    seed: str | None  # the seed the host chose (None: a random one; the runs show it once started)
    timer: int


@dataclass(frozen=True, kw_only=True)
class MatchPlayerView:
    seat: int
    name: str | None
    you: bool
    host: bool
    left: bool = False  # left the match (it is lost)
    id: str | None = None  # their player id (their profile: GET /players/{id})


@dataclass(frozen=True, kw_only=True)
class OpponentView:
    """What a player sees of the other player's run: the public part of their game (no hand, no deck order)."""

    version: int  # the run's version (it changes with each of their actions)
    phase: Phase
    state: str
    ante: int
    round: int
    dollars: Number
    hands_left: int
    discards_left: int
    hand_size: int
    joker_slots: int
    round_score: Score
    blind: BlindView | None
    jokers: list[CardView]
    consumables: int  # how many consumables they hold
    deck_size: int  # cards in their full deck
    full_deck: list[DeckCardView] = field(default_factory=list)  # their whole deck, by suit and rank (not its order)
    deck_remaining: int = 0  # cards left to draw
    vouchers: list[str]
    poker_hands: list[PokerHandView]  # (only the hands they have levelled up or played)
    won: bool


@dataclass(frozen=True, kw_only=True)
class PvPBlindResult:
    """One blind both players have finished, and what it cost them (index = seat)."""

    index: int  # the blind's place in the match (0: the first Small Blind)
    ante: int
    slot: BlindSlot | None
    chips: list[Score]  # each player's score in the round
    target: list[Score]  # each player's blind
    lost: list[bool]  # the player didn't beat the blind
    skipped: list[bool]
    damage: list[int]  # hit points each lost
    hp: list[int]  # each one's hit points after it


@dataclass(frozen=True, kw_only=True)
class BlindVoteView:
    """Playing or skipping the next blind: it is skipped only if both players skip it."""

    index: int  # the blind's place in the match
    yours: BlindChoice | None
    theirs: BlindChoice | None
    decision: BlindChoice | None  # once both have chosen: what both do now


@dataclass(frozen=True, kw_only=True)
class PvPView:
    start_hp: int
    safe_antes: int  # until this ante is over, only a lost round costs hit points
    loss_damage: int  # the hit points a lost round costs
    hp: list[int]  # by seat
    blind_index: int  # your next blind's place in the match (the blinds your run has finished)
    rounds: list[PvPBlindResult]
    vote: BlindVoteView | None  # at the blind select
    # what you are waiting for: "round" (the other player to finish the blind), "vote" (their choice)
    waiting: Literal["round", "vote"] | None
    opponent_waiting: Literal["round", "vote"] | None  # what they are waiting for you to do
    deadline: datetime | None  # when the late player is moved on (the round lost, the shop left ...)
    can_cash_out: bool  # (no: the other player is still playing the round)
    opponent: OpponentView | None


@dataclass(frozen=True, kw_only=True)
class MatchResultView:
    winner: int | None  # the winner's seat; None: a draw (or nobody: the lobby was closed)
    you_won: bool
    reason: str  # "hp" (hit points), "game_over" (a run ended), "left" (a player left), "closed" (the lobby)


@dataclass(frozen=True, kw_only=True)
class CoopMatchView:
    """Coop: one run for both (``run_id``), played in turns."""

    turn: int  # whose turn it is
    your_turn: bool
    selection: list[int]  # the cards the player who selects (``selecting``) has selected, for the other one to watch
    selection_seq: int  # it changes with each new selection
    over: bool  # the run is over (lost)
    selecting: int | None = None  # whose selection it is: the turn's player's, or the pack's opener's while it is open


@dataclass(frozen=True, kw_only=True)
class CoopStep:
    """One action of a coop run, as its player made it, with what the game showed: the other player plays it
    again on their screen."""

    version: int  # the run's version before it
    seat: int  # whose action it was
    action: dict[str, Any]  # as POST /games/{id}/actions takes it (cards by id)
    events: list[FeedbackEvent]
    game: GameView  # the run after it


@dataclass(frozen=True, kw_only=True)
class CoopStepsView:
    steps: list[CoopStep]
    complete: bool  # false: some actions since that version aren't kept (the server restarted): load the run


@dataclass(frozen=True, kw_only=True)
class MatchSummaryPlayer:
    """How the match went for one player (by seat)."""

    seat: int
    name: str | None
    best_hand: Score = 0  # their best single hand (coop: their hands only)
    # PvP
    hp: int | None = None  # hit points left
    damage_dealt: int | None = None  # hit points the other player lost to their chips
    damage_taken: int | None = None
    biggest_hit: int | None = None  # the most hit points their chips took at once
    rounds_won: int | None = None  # blinds where they made more chips than the other player
    rounds_lost: int | None = None  # blinds they lost (not beaten)
    # coop
    hands: int | None = None  # hands they played
    chips: Score | None = None  # the chips their hands scored
    best_hand_name: str | None = None  # (coop) the poker hand of their best hand
    discards: int | None = None


@dataclass(frozen=True, kw_only=True)
class MatchSummaryView:
    """How a finished match went."""

    ante: int  # the furthest ante reached
    rounds: int  # PvP: the blinds both finished; coop: the run's rounds
    run_won: bool | None = None  # coop: the run was won (ante 8 beaten)
    players: list[MatchSummaryPlayer]


@dataclass(frozen=True, kw_only=True)
class RematchView:
    """The match the players of a finished match asked to play next."""

    match_id: str
    code: str
    by_you: bool  # you asked for it (you are its host)
    open: bool  # still in its lobby: join it with POST /matches/{id}/rematch (or its code)


@dataclass(frozen=True, kw_only=True)
class EmoteView:
    seq: int  # it grows with each emote of the match
    seat: int  # who sent it
    emote: EmoteName
    at: datetime


@dataclass(frozen=True, kw_only=True)
class MatchView:
    id: str
    version: int
    code: str  # the invite code (others join with it while in the lobby)
    mode: MatchMode
    status: MatchStatusName
    seat: int  # yours
    host: bool  # you made it (you choose the settings and start it)
    settings: MatchSettingsView
    players: list[MatchPlayerView]
    run_id: str | None  # your run, once started
    run_version: int | None  # its version (a run moved on by the timer has a new one)
    pvp: PvPView | None
    result: MatchResultView | None
    server_time: datetime  # (for the timer's countdown)
    coop: CoopMatchView | None = None
    summary: MatchSummaryView | None = None  # once finished: how it went
    rematch: RematchView | None = None  # once finished: the match its players asked to play next
    emotes: list[EmoteView] = field(default_factory=list)  # the emotes of the last seconds, oldest first


@dataclass(frozen=True, kw_only=True)
class MatchHistoryEntry:
    """A match a player played (finished), as their history lists it."""

    id: str
    mode: MatchMode
    settings: MatchSettingsView
    seed: str | None  # the seed the runs were played with
    created_at: datetime
    finished_at: datetime | None
    seat: int  # the player's
    players: list[MatchPlayerView]
    result: MatchResultView
    summary: MatchSummaryView | None  # (None: a match finished before summaries were kept)
    runs: list[str | None]  # by seat: the runs to watch again (coop: the same run twice)


@dataclass(frozen=True, kw_only=True)
class MatchHistoryView:
    matches: list[MatchHistoryEntry]  # the latest first
    next_before: datetime | None  # for the next page (``before``); None: no more


@dataclass(frozen=True, kw_only=True)
class PvPStats:
    played: int = 0
    won: int = 0
    lost: int = 0
    drawn: int = 0
    gave_up: int = 0  # matches the player left (lost)
    opponent_left: int = 0  # matches won because the other player left
    streak: int = 0  # PvP matches won in a row, up to the latest
    best_streak: int = 0
    damage_dealt: int = 0
    damage_taken: int = 0
    biggest_hit: int = 0
    best_ante: int = 0


@dataclass(frozen=True, kw_only=True)
class CoopStats:
    played: int = 0
    runs_won: int = 0  # coop runs won (ante 8 beaten)
    best_ante: int = 0
    best_round: int = 0
    hands: int = 0  # hands the player played
    chips: Score = 0  # the chips their hands scored
    best_hand: Score = 0
    best_hand_name: str | None = None


@dataclass(frozen=True, kw_only=True)
class MatchOpponentStats:
    """The players someone played with most (PvP: against; coop: with)."""

    id: str  # their player id
    name: str | None
    played: int
    won: int = 0  # PvP: matches the player won against them
    lost: int = 0
    best_ante: int = 0  # coop: the furthest ante together


@dataclass(frozen=True, kw_only=True)
class MultiplayerStats:
    pvp: PvPStats
    coop: CoopStats
    rivals: list[MatchOpponentStats]  # PvP opponents, most played first
    partners: list[MatchOpponentStats]  # coop partners, most played first


@dataclass(frozen=True, kw_only=True)
class CoopDeckView:
    """A coop player's deck: all their playing cards, and those still to draw (by suit and rank, never in order)."""

    seat: int
    full_deck: list[DeckCardView]
    remaining: list[DeckCardView]


@dataclass(frozen=True, kw_only=True)
class CoopDecksView:
    seats: list[CoopDeckView]


# ------------------------------------------------------------------ mods
@dataclass(frozen=True, kw_only=True)
class ModCheck:
    """What the engine says of a package: ``valid``, and if not, ``errors`` (each with its place in the
    package, ``jokers[0].effects[1].if: unknown name 'cardd'``)."""

    valid: bool
    errors: list[str]
    id: str | None = None
    version: str | None = None
    name: str | None = None
    hash: str | None = None  # the package's content hash
    summary: dict[str, Any] = field(default_factory=dict)  # how many jokers, decks ... it has; creative mode
    size: int = 0  # bytes


@dataclass(frozen=True, kw_only=True)
class ModVersionView:
    version: str
    hash: str
    created_at: datetime
    size: int = 0


@dataclass(frozen=True, kw_only=True)
class ModSummaryView:
    """A mod of the registry, as the browser lists it."""

    id: str
    name: str
    version: str  # the latest
    hash: str  # the latest version's package
    description: str
    tags: list[str]
    author: str | None  # the publisher's display name ("Balatro" for the official mods)
    official: bool
    installs: int  # players who installed it
    summary: dict[str, Any]  # jokers, consumables, vouchers, decks, blinds, rules, creative
    created_at: datetime
    updated_at: datetime
    loc: dict[str, Any] = field(default_factory=dict)  # translations of name and description
    yours: bool = False  # the caller published it


@dataclass(frozen=True, kw_only=True)
class ModDetailView(ModSummaryView):
    versions: list[ModVersionView] = field(default_factory=list)  # newest first


@dataclass(frozen=True, kw_only=True)
class ModListView:
    items: list[ModSummaryView]
    total: int
