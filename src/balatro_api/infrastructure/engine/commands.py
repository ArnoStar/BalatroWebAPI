"""Player actions (cards by id) ↔ engine commands (cards by index)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from balatro import Game

from balatro_api.application.dto import AreaName, LegalAction, PlayerAction
from balatro_api.domain import IllegalAction

# where each action looks for its card (engine area names)
BUY_AREAS = ("shop_jokers", "shop_vouchers", "shop_booster")
SELL_AREAS = ("jokers", "consumeables")
MOVE_AREAS = ("jokers", "consumeables", "hand")
AREA_NAMES: dict[str, AreaName] = {"jokers": "jokers", "consumeables": "consumables", "hand": "hand",
                                   "shop_jokers": "shop", "shop_vouchers": "vouchers", "shop_booster": "boosters",
                                   "pack_cards": "pack"}
NO_ARGUMENTS = ("select_blind", "skip_blind", "reroll_boss", "cash_out", "reroll", "end_shop", "skip_pack")
BOSS_REROLL_COST = 10


def _cards(G: Game, name: str) -> list[Any]:
    area = getattr(G, name, None)
    return [] if area is None or area.removed else list(area.cards)


def _index(G: Game, area: str, card_id: int) -> int:
    for i, c in enumerate(_cards(G, area)):
        if c.sort_id == card_id:
            return i
    raise IllegalAction(f"card {card_id} is not in the {AREA_NAMES.get(area, area)}")


def _find(G: Game, areas: Iterable[str], card_id: int | None, action: str) -> tuple[str, int]:
    if card_id is None:
        raise IllegalAction(f"'{action}' needs a card")
    for area in areas:
        for i, c in enumerate(_cards(G, area)):
            if c.sort_id == card_id:
                return area, i
    raise IllegalAction(f"card {card_id} can't be used for '{action}' here")


def _targets(G: Game, targets: Iterable[int] | None) -> list[int] | None:
    return None if targets is None else [_index(G, "hand", t) for t in targets]


def to_command(G: Game, a: PlayerAction) -> dict[str, Any]:
    t = a.type
    if t in NO_ARGUMENTS:
        return {"cmd": t}
    if t == "sort":
        return {"cmd": "sort", "mode": a.mode}
    if t in ("play", "discard"):
        return {"cmd": t, "cards": [_index(G, "hand", c) for c in a.cards]}
    if t == "buy":
        area, i = _find(G, BUY_AREAS, a.card, t)
        return {"cmd": "buy", "area": area, "index": i, **({"use": True} if a.use else {})}
    if t == "sell":
        area, i = _find(G, SELL_AREAS, a.card, t)
        return {"cmd": "sell", "area": area, "index": i}
    if t == "use":
        _, i = _find(G, ("consumeables",), a.card, t)
        return {"cmd": "use", "index": i, "targets": _targets(G, a.targets)}
    if t == "pick":
        _, i = _find(G, ("pack_cards",), a.card, t)
        return {"cmd": "pick", "index": i, "targets": _targets(G, a.targets)}
    if t == "move":
        area, i = _find(G, MOVE_AREAS, a.card, t)
        if a.to is None:
            raise IllegalAction("'move' needs the new position 'to'")
        return {"cmd": "move", "area": area, "from": i, "to": a.to}
    raise IllegalAction(f"unknown action {t!r}")


def legal_actions(G: Game) -> list[LegalAction]:
    out: list[LegalAction] = []
    cr = G.GAME.current_round
    for a in G.legal_actions():
        cmd = a["cmd"]
        if cmd == "reroll_boss":
            out.append(LegalAction(type=cmd, cost=BOSS_REROLL_COST))
        elif cmd in NO_ARGUMENTS and cmd != "reroll":
            out.append(LegalAction(type=cmd))
        elif cmd == "reroll":
            out.append(LegalAction(type=cmd, cost=cr.reroll_cost))
        elif cmd in ("play", "discard"):
            out.append(LegalAction(type=cmd, min_cards=1, max_cards=G.hand.config.highlighted_limit))
        elif cmd == "sort":
            out.append(LegalAction(type=cmd, mode=a["mode"]))
        elif cmd == "buy":
            c = _cards(G, a["area"])[a["index"]]
            out.append(LegalAction(type=cmd, card=c.sort_id, area=AREA_NAMES[a["area"]], use=bool(a.get("use")),
                                   cost=c.cost))
        elif cmd == "sell":
            c = _cards(G, a["area"])[a["index"]]
            out.append(LegalAction(type=cmd, card=c.sort_id, area=AREA_NAMES[a["area"]], value=c.sell_cost))
        elif cmd in ("use", "pick"):
            c = _cards(G, "consumeables" if cmd == "use" else "pack_cards")[a["index"]]
            out.append(LegalAction(type=cmd, card=c.sort_id, area="consumables" if cmd == "use" else "pack",
                                   min_targets=a.get("min"), max_targets=a.get("max")))
    if not G.is_game_over():
        for area in MOVE_AREAS:
            if len(_cards(G, area)) >= 2:
                out.append(LegalAction(type="move", area=AREA_NAMES[area]))
    return out
