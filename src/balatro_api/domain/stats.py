"""What a run adds to its player's statistics.

The game keeps a profile per player: career stats (cards played, money
earned ...), high scores (best hand, highest ante ...) and how often each
poker hand, joker, consumable and voucher was used. ``RunStats`` is one run's
part of it, as the engine counts it. Like ``Progress``, it is derived from
the run's commands and kept with the run so statistics never need a replay.

As in the game, a run only counts for statistics and leaderboards when the
player didn't choose its seed and it isn't a challenge; and here, when no
debug command was used in it (``Run.counts``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

# the career stats that add up over runs (the game's G.PROFILES[...].career_stats
# without its two streaks, which only make sense across runs)
CAREER_STATS = ("c_dollars_earned", "c_shop_dollars_spent", "c_tarots_bought", "c_planets_bought",
                "c_playing_cards_bought", "c_vouchers_bought", "c_tarot_reading_used", "c_planetarium_used",
                "c_shop_rerolls", "c_cards_played", "c_cards_discarded", "c_losses", "c_wins", "c_rounds",
                "c_hands_played", "c_face_cards_played", "c_jokers_sold", "c_cards_sold")


@dataclass(frozen=True)
class JokerUsage:
    """One joker in one run: in how many won rounds the player had it (the
    game's joker usage), and how many copies were held when the run was won
    or lost."""

    rounds: int = 0
    wins: int = 0
    losses: int = 0


@dataclass(frozen=True)
class RunStats:
    """The run's high scores and what it added to the player's profile."""

    best_hand: float = 0  # the best single hand's score (can be inf, like the game's "naneinf")
    furthest_ante: int = 0
    furthest_round: int = 0
    most_money: float = 0
    boss_streak: int = 0  # boss blinds beaten in a row (without playing a Small or Big blind in between)
    career: Mapping[str, float] = field(default_factory=dict)  # CAREER_STATS -> amount
    hands: Mapping[str, int] = field(default_factory=dict)  # poker hand -> times played
    jokers: Mapping[str, JokerUsage] = field(default_factory=dict)  # joker key
    consumables: Mapping[str, int] = field(default_factory=dict)  # consumable key -> times used
    vouchers: Mapping[str, int] = field(default_factory=dict)  # voucher key -> times redeemed

    def to_json(self) -> dict[str, object]:
        """The parts kept as a JSON document (the high scores have their own columns)."""
        return {"career": dict(self.career), "hands": dict(self.hands), "consumables": dict(self.consumables),
                "vouchers": dict(self.vouchers),
                "jokers": {k: [u.rounds, u.wins, u.losses] for k, u in self.jokers.items()}}

    @staticmethod
    def from_json(doc: Mapping[str, object], *, best_hand: float, furthest_ante: int, furthest_round: int,
                  most_money: float, boss_streak: int) -> RunStats:
        def counts(key: str) -> dict[str, int]:
            v = doc.get(key)
            return {str(k): int(n) for k, n in v.items()} if isinstance(v, Mapping) else {}

        career = doc.get("career")
        jokers = doc.get("jokers")
        return RunStats(
            best_hand=best_hand, furthest_ante=furthest_ante, furthest_round=furthest_round, most_money=most_money,
            boss_streak=boss_streak,
            career={str(k): float(v) for k, v in career.items()} if isinstance(career, Mapping) else {},
            hands=counts("hands"), consumables=counts("consumables"), vouchers=counts("vouchers"),
            jokers={str(k): JokerUsage(*(int(x) for x in v)) for k, v in jokers.items()}
            if isinstance(jokers, Mapping) else {})
