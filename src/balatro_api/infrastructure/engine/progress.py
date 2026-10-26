"""The player's progress (the game's G.PROFILES and the centers' unlocked and
discovered flags), kept the way the statistics are: derived from the player's
runs.

A run started from the player's progress (``Run.start_profile``) adds to it
as the game would: an unseeded run that isn't a challenge with what it
unlocked and discovered, its career stats, voucher usage and the deck's win
or loss; a won challenge with its completion. Runs from before progress was
kept, fully unlocked runs (testers), replays and runs with debug commands add
nothing. The rules are the engine's (balatro.progress); this only adds runs up.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from balatro import Profile
from balatro.data import load

from balatro_api.application.dto import CollectionCount, CollectionView, ProgressView
from balatro_api.domain import GameSettings, Locked, Phase, RunSummary


def player_profile(runs: Sequence[RunSummary]) -> Profile:
    p = Profile.fresh()
    streak_at: dict[str, datetime] = {}
    for r in sorted(runs, key=lambda r: r.created_at):
        if not r.tracks_progress or r.debug or r.replay:
            continue
        s = r.settings
        if s.challenge is not None:
            if r.progress.won:
                p.challenges_completed.add(s.challenge)
            continue
        if s.seeded:
            continue
        st = r.stats
        p.unlocked.update(st.unlocked)
        p.discovered.update(st.discovered)
        for k, v in st.career.items():
            p.career_stats[k] = (p.career_stats.get(k) or 0) + v
        for k, n in st.vouchers.items():
            p.voucher_usage[k] = (p.voucher_usage.get(k) or 0) + n
        usage = p.deck_usage.setdefault(s.deck, {"wins": {}, "losses": {}})
        if r.progress.won:  # set_deck_win
            wins = usage["wins"]
            wins[s.stake] = (wins.get(s.stake) or 0) + 1
            for i in range(1, s.stake + 1):
                wins[i] = wins.get(i) or 1
        elif r.progress.phase is Phase.GAME_OVER:  # set_deck_loss
            usage["losses"][s.stake] = (usage["losses"].get(s.stake) or 0) + 1
        for k, v in st.streaks.items():  # the streaks span runs: the latest value
            if k not in streak_at or r.updated_at >= streak_at[k]:
                streak_at[k] = r.updated_at
                p.career_stats[k] = v
    return p.with_main_menu_unlocks()


def check_unlocked(settings: GameSettings, p: Profile) -> None:
    """What the game's run setup offers: an unlocked deck, a stake up to the one
    after the deck's best win, a challenge among the open ones."""
    data = load()
    if settings.challenge is not None:
        ids = [c.id for c in data.challenges]
        if settings.challenge in ids and ids.index(settings.challenge) >= p.challenges_unlocked(len(ids)):
            raise Locked(f"the challenge {settings.challenge!r} is locked")
        return
    if not p.is_unlocked(settings.deck):
        raise Locked(f"the deck {settings.deck!r} is locked")
    if settings.stake > p.max_stake(settings.deck):
        raise Locked(f"stake {settings.stake} isn't unlocked with this deck yet (win stake {settings.stake - 1} first)")


def _decks() -> list[str]:
    return [c.key for c in load().P_CENTER_POOLS["Back"] if not c.omit]


def progress_view(p: Profile, all_unlocked: bool, can_unlock_all: bool) -> ProgressView:
    data = load()
    total = len(data.challenges)
    everything = p.all or all_unlocked
    return ProgressView(
        all_unlocked=all_unlocked, can_unlock_all=can_unlock_all,
        unlocked=sorted(k for k, v in data.P_CENTERS.items() if v.unlocked is False and p.is_unlocked(k)),
        discovered=sorted(p.discovered), challenges_completed=sorted(p.challenges_completed),
        challenges_unlocked=total if everything else p.challenges_unlocked(total),
        deck_stakes={d: p.deck_win_stake(d) for d in _decks() if p.deck_win_stake(d) > 0} if not p.all else {},
        max_stakes={d: 8 if everything else p.max_stake(d) for d in _decks()})


def collection_view(p: Profile) -> CollectionView:
    data = load()

    def count(keys: list[str]) -> CollectionCount:
        return CollectionCount(found=sum(1 for k in keys if p.all or k in p.discovered), total=len(keys))

    def by_set(kind: str) -> list[str]:
        return [k for k, v in data.P_CENTERS.items() if v.set == kind and not v.omit]
    decks = _decks()
    return CollectionView(
        jokers=count(by_set("Joker")), tarots=count(by_set("Tarot")), planets=count(by_set("Planet")),
        spectrals=count(by_set("Spectral")), vouchers=count(by_set("Voucher")), boosters=count(by_set("Booster")),
        editions=count(by_set("Edition")), blinds=count(list(data.P_BLINDS)), tags=count(list(data.P_TAGS)),
        decks=CollectionCount(found=sum(1 for d in decks if p.is_unlocked(d)), total=len(decks)),
        challenges=CollectionCount(found=len(p.challenges_completed) if not p.all else 0, total=len(data.challenges)),
        deck_stakes={d: p.deck_win_stake(d) for d in decks if not p.all and p.deck_win_stake(d) > 0})
