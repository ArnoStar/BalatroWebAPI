"""The engine's game → the application's views (what the player can see)."""

from __future__ import annotations

from typing import Any, Literal

from balatro import STATE_NAMES, STATES, Game
from balatro.snapshot import JOKER_ABILITY_KEYS

from balatro_api.application.dto import (
    AreaName,
    BlindChoiceView,
    BlindSelectView,
    BlindView,
    CardFlippedEvent,
    CardJuicedEvent,
    CardKind,
    CardMovedEvent,
    CardRemovedEvent,
    CardTextEvent,
    CardView,
    DeckCardView,
    DeckView,
    DollarsEvent,
    FeedbackEvent,
    GameView,
    HandPanelEvent,
    HandScore,
    HandScoredEvent,
    PackView,
    PokerHandView,
    RoundEvalRow,
    RoundEvalView,
    RoundScoreEvent,
    RoundTargets,
    RunInfo,
    SettingsView,
    ShopView,
    StatusTextEvent,
    Stickers,
    TagView,
)
from balatro_api.domain import CAREER_STATS, JokerUsage, Phase, Progress, Run, RunStats

from .commands import legal_actions

AREA_NAMES: dict[str, AreaName] = {
    "deck": "deck", "hand": "hand", "play": "play", "discard": "discard", "jokers": "jokers",
    "consumeables": "consumables", "shop_jokers": "shop", "shop_vouchers": "vouchers", "shop_booster": "boosters",
    "pack_cards": "pack",
}
CARD_KINDS: dict[str, CardKind] = {
    "Default": "playing_card", "Enhanced": "playing_card", "Joker": "joker", "Tarot": "tarot", "Planet": "planet",
    "Spectral": "spectral", "Voucher": "voucher", "Booster": "booster",
}
PackKind = Literal["tarot", "planet", "spectral", "standard", "buffoon"]
PACK_KINDS: dict[int, PackKind] = {
    STATES.TAROT_PACK: "tarot", STATES.PLANET_PACK: "planet", STATES.SPECTRAL_PACK: "spectral",
    STATES.STANDARD_PACK: "standard", STATES.BUFFOON_PACK: "buffoon",
}
PHASES = {STATES.BLIND_SELECT: Phase.BLIND_SELECT, STATES.SELECTING_HAND: Phase.PLAYING,
          STATES.ROUND_EVAL: Phase.ROUND_EVAL, STATES.SHOP: Phase.SHOP, STATES.GAME_OVER: Phase.GAME_OVER,
          **{s: Phase.PACK for s in PACK_KINDS}}
SUIT_ORDER = {"Spades": 0, "Hearts": 1, "Clubs": 2, "Diamonds": 3}


def phase(G: Game) -> Phase:
    try:
        return PHASES[G.STATE]
    except KeyError:  # the engine settles before returning, so this is a bug
        raise RuntimeError(f"the game is not waiting for the player (state {STATE_NAMES.get(G.STATE)})") from None


def progress(G: Game) -> Progress:
    GAME = G.GAME
    return Progress(phase=phase(G), ante=GAME.round_resets.ante, round=GAME.round, dollars=GAME.dollars,
                    won=bool(GAME.won))


def run_stats(G: Game) -> RunStats:
    """What the run has added to the player's profile (the engine's
    ``G.PROFILE``, the game's career stats, high scores and usage)."""
    P = G.PROFILE
    hs = P.high_scores
    return RunStats(
        best_hand=float(hs.hand or 0), furthest_ante=int(hs.furthest_ante or 0),
        furthest_round=int(hs.furthest_round or 0), most_money=float(hs.most_money or 0),
        boss_streak=int(hs.boss_streak or 0),
        career={k: float(P.career_stats.get(k) or 0) for k in CAREER_STATS},
        hands={str(u.order): int(u.count) for u in G.GAME.hand_usage.values()},
        consumables={str(k): int(u.count) for k, u in G.GAME.consumeable_usage.items()},
        vouchers={str(k): int(n) for k, n in P.voucher_usage.items()},
        jokers={str(k): JokerUsage(rounds=int(u.count), wins=int(sum(u.wins.values())),
                                   losses=int(sum(u.losses.values())))
                for k, u in P.joker_usage.items()})


def plain(v: Any) -> Any:
    """Engine tables (dict subclasses) and lists as plain JSON-able data."""
    if isinstance(v, dict):
        return {str(k): plain(x) for k, x in v.items() if not callable(x)}
    if isinstance(v, (list, tuple)):
        return [plain(x) for x in v]
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return str(v)


# ------------------------------------------------------------------ cards
def _joker_ability(ab: Any) -> dict[str, Any]:
    out: dict[str, Any] = {k: ab.get(k) for k in JOKER_ABILITY_KEYS if ab.get(k) is not None}
    if isinstance(ab.extra, dict):
        out["extra"] = {k: v for k, v in ab.extra.items() if isinstance(v, (int, float, str, bool))}
    elif ab.extra is not None:
        out["extra"] = ab.extra
    return out


def card_view(G: Game, c: Any, area: str, face_up: bool = False) -> CardView:
    """The card as it shows (``face_up``: its front, even if it is turned over now)."""
    ab = c.ability
    kind = CARD_KINDS.get(ab.set, "playing_card")
    if c.facing == "back" and not face_up:
        return CardView(id=c.sort_id, kind=kind, face_down=True, selected=bool(c.highlighted))
    center = c.config.center
    playing = kind == "playing_card"
    stickers = None
    if ab.eternal or ab.perishable or ab.rental:
        stickers = Stickers(eternal=bool(ab.eternal), perishable=ab.perish_tally if ab.perishable else None,
                            rental=bool(ab.rental))
    in_shop = area in ("shop_jokers", "shop_vouchers", "shop_booster")
    return CardView(
        id=c.sort_id,
        kind=kind,
        key=center.key,
        name=G.P_CARDS[c.config.card_key].name if playing and c.config.card_key else G.data.display_name(center.key),
        rank=c.base.value if playing else None,
        suit=c.base.suit if playing else None,
        card_key=c.config.card_key if playing else None,
        enhancement=center.key if playing and center.key != "c_base" else None,
        edition=c.edition.type if c.edition else None,
        seal=c.seal,
        stickers=stickers,
        rarity=center.rarity if kind == "joker" else None,
        debuffed=bool(c.debuff),
        selected=bool(c.highlighted),
        forced_selection=bool(ab.forced_selection),
        cost=c.cost if in_shop else None,
        sell_value=c.sell_cost if area in ("jokers", "consumeables") else None,
        bonus_chips=(ab.perma_bonus or None) if playing else None,
        ability=_joker_ability(ab) if kind == "joker" else None,
    )


def cards_view(G: Game, area: Any) -> list[CardView]:
    if area is None or area.removed:
        return []
    return [card_view(G, c, area.name) for c in area.cards]


def deck_view(G: Game) -> DeckView:
    def key(c: Any) -> tuple[int, int]:
        return SUIT_ORDER.get(c.base.suit, 4), -(c.base.id or 0)
    cards = [DeckCardView(key=c.config.center.key, card_key=c.config.card_key, rank=c.base.value, suit=c.base.suit,
                          enhancement=c.config.center.key if c.config.center.key != "c_base" else None,
                          edition=c.edition.type if c.edition else None, seal=c.seal)
             for c in sorted(G.deck.cards, key=key)]
    return DeckView(remaining=len(G.deck.cards), total=len(G.playing_cards), cards=cards)


# ------------------------------------------------------------------ blinds
def _tag(G: Game, t: Any) -> TagView:
    return TagView(key=t.key, name=G.data.display_name(t.key),
                   orbital_hand=t.ability.orbital_hand if t.key == "tag_orbital" else None)


def blind_select_view(G: Game) -> BlindSelectView | None:
    if G.STATE != STATES.BLIND_SELECT:
        return None
    GAME = G.GAME
    rr = GAME.round_resets
    no_reward = GAME.modifiers.no_blind_reward or {}
    choices = []
    for slot in ("Small", "Big", "Boss"):
        key = rr.blind_choices[slot]
        proto = G.P_BLINDS[key]
        tag_key = (rr.blind_tags or {}).get(slot) if slot != "Boss" else None
        choices.append(BlindChoiceView(
            slot=slot, key=key, name=G.data.display_name(key), state=rr.blind_states[slot],
            chips=G.get_blind_amount(rr.blind_ante) * proto.mult * GAME.starting_params.ante_scaling,
            reward=0 if no_reward.get(slot) else proto.dollars,
            skip_tag=TagView(key=tag_key, name=G.data.display_name(tag_key)) if tag_key else None))
    return BlindSelectView(on_deck=GAME.blind_on_deck or "Small", choices=choices,
                           boss_reroll_cost=10 if G.can_reroll_boss() else None)


def blind_view(G: Game) -> BlindView | None:
    b = G.GAME.blind
    if G.STATE not in (STATES.SELECTING_HAND, STATES.ROUND_EVAL) or b is None or not b.config.blind:
        return None
    key = b.config.blind.key
    return BlindView(key=key, name=G.data.display_name(key), slot=b.get_type(), chips=b.chips, reward=b.dollars,
                     boss=bool(b.boss), disabled=bool(b.disabled))


# ------------------------------------------------------------------ rest
def round_eval_view(G: Game) -> RoundEvalView | None:
    if G.STATE != STATES.ROUND_EVAL or not G.round_eval_rows:
        return None
    rows = []
    for label, dollars in G.round_eval_rows:
        kind, _, key = label.partition(":")
        rows.append(RoundEvalRow(kind=kind, dollars=dollars, key=key or None))
    return RoundEvalView(rows=rows, total=sum(r.dollars for r in rows))


def shop_view(G: Game) -> ShopView | None:
    if not G.in_shop():
        return None
    cr = G.GAME.current_round
    return ShopView(jokers=cards_view(G, G.shop_jokers), vouchers=cards_view(G, G.shop_vouchers),
                    boosters=cards_view(G, G.shop_booster), reroll_cost=cr.reroll_cost,
                    free_rerolls=cr.free_rerolls or 0)


def pack_view(G: Game) -> PackView | None:
    if not G.in_pack() or G.pack_cards is None or G.pack_cards.removed:
        return None
    return PackView(kind=PACK_KINDS[G.STATE], cards=cards_view(G, G.pack_cards), choices_left=G.GAME.pack_choices or 0)


def poker_hands_view(G: Game) -> list[PokerHandView]:
    proto = G.data.hands_proto
    names = G.data.poker_hand_names
    return [PokerHandView(name=k, display_name=names.get(k, k), level=h.level, chips=h.chips, mult=h.mult,
                          played=h.played, visible=bool(h.visible))
            for k, h in sorted(G.GAME.hands.items(), key=lambda kv: proto[kv[0]]["order"])]


def info_view(G: Game) -> RunInfo:
    GAME = G.GAME
    cr = GAME.current_round
    targets = RoundTargets(
        idol_rank=cr.idol_card.rank if cr.idol_card else None, idol_suit=cr.idol_card.suit if cr.idol_card else None,
        mail_rank=cr.mail_card.rank if cr.mail_card else None,
        ancient_suit=cr.ancient_card.suit if cr.ancient_card else None,
        castle_suit=cr.castle_card.suit if cr.castle_card else None,
        most_played_hand=cr.most_played_poker_hand)
    return RunInfo(probability_normal=GAME.probabilities.normal, last_tarot_planet=GAME.last_tarot_planet,
                   interest_amount=GAME.interest_amount, interest_cap=GAME.interest_cap,
                   discount_percent=GAME.discount_percent, bankrupt_at=GAME.bankrupt_at, skips=GAME.skips or 0,
                   hands_played=GAME.hands_played or 0, unused_discards=GAME.unused_discards or 0,
                   round_targets=targets)


def game_view(run: Run, G: Game) -> GameView:
    GAME = G.GAME
    cr = GAME.current_round
    s = run.settings
    last = G.last_score
    return GameView(
        id=run.id,
        version=run.version,
        settings=SettingsView(seed=s.seed, deck=s.deck, stake=s.stake, challenge=s.challenge, game_speed=s.game_speed,
                              seeded=s.seeded),
        phase=phase(G),
        state=STATE_NAMES.get(G.STATE, str(G.STATE)),
        won=bool(GAME.won),
        ante=GAME.round_resets.ante,
        round=GAME.round,
        dollars=GAME.dollars,
        hands_left=cr.hands_left,
        discards_left=cr.discards_left,
        hand_size=G.hand.config.card_limit,
        joker_slots=G.jokers.config.card_limit,
        consumable_slots=G.consumeables.config.card_limit,
        round_score=GAME.chips,
        blind=blind_view(G),
        blind_select=blind_select_view(G),
        hand=cards_view(G, G.hand),
        jokers=cards_view(G, G.jokers),
        consumables=cards_view(G, G.consumeables),
        deck=deck_view(G),
        discard_count=len(G.discard.cards),
        shop=shop_view(G),
        pack=pack_view(G),
        round_eval=round_eval_view(G),
        tags=[_tag(G, t) for t in GAME.tags],
        vouchers=[k for k, v in GAME.used_vouchers.items() if v],
        poker_hands=poker_hands_view(G),
        last_hand=HandScore(hand=last.hand, chips=last.chips, mult=last.mult, score=last.score) if last else None,
        info=info_view(G),
        actions=legal_actions(G),
    )


# ------------------------------------------------------------------ feedback
def _find_card(G: Game, card_id: int) -> tuple[Any, str] | None:
    """A card of the run by sort_id, with its area's name."""
    for area in (G.hand, G.deck, G.play, G.discard, G.jokers, G.consumeables, G.pack_cards, G.shop_jokers,
                 G.shop_vouchers, G.shop_booster):
        if area is None or area.removed:
            continue
        for c in area.cards:
            if c.sort_id == card_id:
                return c, area.name
    return None


def feedback_events(entries: list[dict[str, Any]], G: Game | None = None) -> list[FeedbackEvent]:
    """The action's feedback as events; ``G`` (the game after the action) gives the cards turned face up."""
    out: list[FeedbackEvent] = []
    for e in entries:
        kind, t = e["type"], e["t"]
        if kind == "hand":
            out.append(HandPanelEvent(t=t, hand=e.get("handname"), level=e.get("level"), chips=e.get("chips"),
                                      mult=e.get("mult"), hand_score=e.get("chip_total")))
        elif kind == "card_text":
            out.append(CardTextEvent(t=t, card=e.get("card"), effect=e["effect"], amount=e.get("amount"),
                                     message=e.get("message"), held=bool(e.get("held")),
                                     edition=bool(e.get("edition"))))
        elif kind == "hand_scored":
            out.append(HandScoredEvent(t=t, hand=e["hand"], chips=e["chips"], mult=e["mult"], score=e["score"],
                                       round_score=e["round_score"]))
        elif kind == "round_score":
            out.append(RoundScoreEvent(t=t, chips=e["chips"]))
        elif kind == "dollars":
            out.append(DollarsEvent(t=t, amount=e["amount"], total=e["total"]))
        elif kind == "status_text":
            out.append(StatusTextEvent(t=t, text=e["text"]))
        elif kind == "card_moved" and e["to"] in AREA_NAMES:
            out.append(CardMovedEvent(t=t, card=e["card"], to=AREA_NAMES[e["to"]]))
        elif kind == "card_flipped":
            face_down = e["facing"] == "back"
            found = None if face_down or G is None else _find_card(G, e["card"])
            view = card_view(G, found[0], found[1], face_up=True) if G is not None and found else None
            out.append(CardFlippedEvent(t=t, card=e["card"], face_down=face_down, view=view))
        elif kind == "card_juiced":
            out.append(CardJuicedEvent(t=t, card=e["card"]))
        elif kind == "card_removed" and e["area"] in AREA_NAMES:
            out.append(CardRemovedEvent(t=t, card=e["card"], area=AREA_NAMES[e["area"]]))
    return out
