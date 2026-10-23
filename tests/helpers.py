"""Shared test helpers."""

from __future__ import annotations

import random
from typing import Any


def concrete(game: dict[str, Any], legal: dict[str, Any], rnd: random.Random) -> dict[str, Any] | None:
    """A random full action from a legal action of a GameView (JSON)."""
    hand = [c["id"] for c in game["hand"]]
    t = legal["type"]
    a: dict[str, Any] = {"type": t}
    if t in ("play", "discard"):
        forced = [c["id"] for c in game["hand"] if c["forced_selection"]]
        rest = [i for i in hand if i not in forced]
        a["cards"] = forced + rnd.sample(rest, rnd.randint(0 if forced else 1, min(5 - len(forced), len(rest))))
    elif t == "sort":
        a["mode"] = legal["mode"]
    elif t in ("buy", "sell"):
        a["card"] = legal["card"]
        if legal.get("use"):
            a["use"] = True
    elif t in ("use", "pick"):
        a["card"] = legal["card"]
        if legal.get("max_targets"):
            lo, hi = legal["min_targets"], legal["max_targets"]
            if len(hand) < lo:
                return None
            a["targets"] = rnd.sample(hand, rnd.randint(lo, min(hi, len(hand))))
    elif t == "move":
        area = {"jokers": game["jokers"], "consumables": game["consumables"], "hand": game["hand"]}[legal["area"]]
        a["card"] = rnd.choice(area)["id"]
        a["to"] = rnd.randrange(len(area))
    return a
