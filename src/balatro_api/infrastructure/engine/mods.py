"""Content mods with the engine: checking a package (its format, then a short
run played with it), what it holds, and the examples that come with the engine."""

from __future__ import annotations

import random
from typing import Any

import balatro
from balatro import Game
from balatro.mods import examples
from balatro.mods.content import ModError
from balatro.mods.spec import PREFIX, full_key, logic, validate

PLAY_STEPS = 120  # the short run a new package is played for
KINDS = ("jokers", "consumables", "vouchers", "decks", "blinds")


def summary(package: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {k: len(package.get(k) or []) for k in KINDS}
    out["rules"] = bool(package.get("rules"))
    out["creative"] = bool(package.get("creative"))
    out["decks_keys"] = [full_key(package["id"], "decks", d["key"]) for d in package.get("decks") or []
                         if isinstance(d, dict) and "key" in d] if isinstance(package.get("id"), str) else []
    return out


def _play(G: Game, rng: random.Random, steps: int) -> None:
    for _ in range(steps):
        if G.is_game_over():
            return
        actions = [a for a in G.legal_actions() if a["cmd"] not in ("creative", "sell")]
        if not actions:
            return
        a = dict(rng.choice(actions))
        if a["cmd"] in ("play", "discard"):
            n = len(G.hand.cards)
            a = {"cmd": a["cmd"], "cards": sorted(rng.sample(range(n), min(n, rng.randint(1, 5))))}
        elif "min" in a:
            n = min(a.pop("max"), len(G.hand.cards))
            a.pop("min")
            a["targets"] = list(range(n))
        try:
            G.do(a)
        except balatro.IllegalAction:
            continue


def check(package: dict[str, Any], play: bool = True) -> list[str]:
    """What is wrong with a package: the format, then a short run on each of its decks (with its jokers,
    consumables and vouchers given at the start) that must not fail."""
    errors: list[str] = validate(package)
    if errors or not play:
        return errors
    pkg = logic(package)
    mod_id = pkg["id"]
    decks = [full_key(mod_id, "decks", d["key"]) for d in pkg.get("decks", [])] or ["b_red"]
    items = [(full_key(mod_id, kind, it["key"]), kind) for kind in ("jokers", "consumables", "vouchers")
             for it in pkg.get(kind, [])]
    try:
        for n, deck in enumerate(decks):
            rng = random.Random(n)
            G = Game("MODCHECK", deck=deck, mods=[pkg]).start_run()
            for key, kind in items:  # (through the engine's test helpers: the run isn't anyone's)
                if kind == "vouchers":
                    G.do({"cmd": "add_voucher", "key": key})
                elif kind == "jokers" and len(G.jokers.cards) < G.jokers.config.card_limit:
                    G.do({"cmd": "add_joker", "key": key})
                elif kind == "consumables" and len(G.consumeables.cards) < G.consumeables.config.card_limit:
                    G.do({"cmd": "add_joker", "key": key})
            for b in pkg.get("blinds", []):
                G.do({"cmd": "cheat", "boss": full_key(mod_id, "blinds", b["key"])})
                break
            _play(G, rng, PLAY_STEPS)
    except ModError as e:
        return list(e.errors)
    except Exception as e:  # (a bug of the engine or the package: either way the mod can't be played)
        return [f"playing it failed: {type(e).__name__}: {e}"]
    return []


def official() -> list[dict[str, Any]]:
    return list(examples().values())


__all__ = ["PREFIX", "check", "official", "summary"]
