"""The static game data a front end needs, from the engine's data files."""

from __future__ import annotations

from typing import Any

import balatro
from balatro.data import load, sprites

from balatro_api.application.dto import (
    AtlasView,
    BlindItem,
    Catalog,
    CatalogItem,
    ChallengeItem,
    PlayingCardItem,
    PokerHandItem,
    Sprite,
    SpritePos,
    StakeItem,
    TagItem,
)

from .presenter import plain


def _sprite(entry: dict[str, Any] | None) -> Sprite | None:
    if not entry or not entry.get("pos"):
        return None
    soul = entry.get("soul_pos")
    return Sprite(atlas=entry["atlas"], pos=SpritePos(**entry["pos"]),
                  soul_pos=SpritePos(**soul) if soul else None)


def _ids(items: Any) -> list[str]:
    return [i.id for i in items] if isinstance(items, list) else []


def build_catalog() -> Catalog:
    d = load()
    sp = sprites()

    def item(c: Any) -> CatalogItem:
        config = plain(c.config) if c.config else None
        if c.set == "Booster":
            config = {**(config or {}), "kind": c.kind}
        return CatalogItem(key=c.key, name=d.display_name(c.key), set=c.set, sprite=_sprite(sp["centers"].get(c.key)),
                           cost=c.cost, rarity=c.rarity if c.set == "Joker" else None, config=config or None,
                           requires=list(c.requires) if c.requires else None)

    def pool(name: str) -> list[CatalogItem]:
        return [item(c) for c in d.P_CENTER_POOLS[name]]

    challenges = []
    for ch in d.challenges:
        deck = d.center_by_name(ch.deck.type) if ch.deck and ch.deck.type else None
        challenges.append(ChallengeItem(id=ch.id, name=ch.name, deck=deck.key if deck else "b_red",
                                        jokers=_ids(ch.jokers), consumables=_ids(ch.consumeables),
                                        vouchers=_ids(ch.vouchers)))

    blinds = [BlindItem(key=k, name=d.display_name(k), boss=bool(b.boss), showdown=bool(b.boss and b.boss.showdown),
                        min_ante=b.boss.min if b.boss else None, dollars=b.dollars, mult=b.mult,
                        colour=sp["blinds"].get(k, {}).get("colour"), sprite=_sprite(sp["blinds"].get(k)))
              for k, b in sorted(d.P_BLINDS.items(), key=lambda kv: kv[1].order)]
    hands = sorted(d.hands_proto.items(), key=lambda kv: kv[1]["order"])

    return Catalog(
        game_version=d.version,
        engine_version=balatro.__version__,
        decks=pool("Back"),
        challenge_deck=item(d.P_CENTERS["b_challenge"]),
        stakes=[StakeItem(level=s.stake_level, key=k, name=s.name, sprite=_sprite(sp["stakes"].get(k)))
                for k, s in sorted(d.P_STAKES.items(), key=lambda kv: kv[1].stake_level)],
        challenges=challenges,
        jokers=pool("Joker"),
        tarots=pool("Tarot"),
        planets=pool("Planet"),
        spectrals=pool("Spectral"),
        vouchers=pool("Voucher"),
        boosters=pool("Booster"),
        enhancements=pool("Enhanced"),
        editions=[item(c) for c in d.P_CENTER_POOLS["Edition"] if c.key != "e_base"],
        seals=[CatalogItem(key=k, name=f"{k} Seal", set="Seal", sprite=_sprite(sp["seals"].get(k)))
               for k, _ in sorted(d.P_SEALS.items(), key=lambda kv: kv[1].order)],
        stickers={k: s for k, v in sp["stickers"].items() if (s := _sprite(v))},
        tags=[TagItem(key=k, name=d.display_name(k), min_ante=t.min_ante, sprite=_sprite(sp["tags"].get(k)))
              for k, t in sorted(d.P_TAGS.items(), key=lambda kv: kv[1].order)],
        blinds=blinds,
        poker_hands=[PokerHandItem(name=k, display_name=d.poker_hand_names.get(k, k), chips=h["s_chips"],
                                   mult=h["s_mult"], level_chips=h["l_chips"], level_mult=h["l_mult"],
                                   visible=bool(h["visible"])) for k, h in hands],
        cards=[PlayingCardItem(key=k, name=c.name, rank=c.value, suit=c.suit, sprite=_sprite(sp["cards"].get(k)))
               for k, c in sorted(d.P_CARDS.items())],
        atlases={k: AtlasView(**v) for k, v in sp["atlases"].items()},
    )
