"""The GameEngine port, implemented with BalatroEngine.

The engine's games are kept in memory (an LRU cache keyed by run id, tagged
with the run version they are at).  A run that is not in the cache, or is at
another version (another server process played it), is rebuilt by replaying
its commands: the engine is deterministic, so that gives exactly the same
game.  Actions are played on a copy (``Game.clone()``) and the copy replaces
the cached game only once the run is saved (``commit``).
"""

from __future__ import annotations

import random
import threading
from collections import OrderedDict
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from functools import cached_property
from typing import Any

import balatro
from balatro import DECK_NAMES, Game
from balatro.data import load
from balatro.rng import SEED_ALPHABET, normalize_seed

from balatro_api.application.dto import Catalog, GameView, HandPreview, LegalAction, PlayerAction
from balatro_api.application.locks import RunLocks
from balatro_api.application.ports import Outcome
from balatro_api.domain import Command, GameSettings, IllegalAction, InvalidGameSettings, Progress, Run, RunStats

from . import presenter
from .catalog import build_catalog
from .commands import legal_actions, to_command

DEBUG_COMMANDS = ("cheat", "add_joker", "add_tag", "add_voucher")


class ReplayFailed(RuntimeError):
    """A stored run doesn't replay (its commands came from another engine version?)."""

    def __init__(self, run_id: str, index: int, error: Exception) -> None:
        super().__init__(f"run {run_id}: command #{index} doesn't replay: {error!r}")


class BalatroEngine:
    def __init__(self, cache_size: int = 256) -> None:
        self.cache_size = cache_size
        self._cache: OrderedDict[str, tuple[int, Game]] = OrderedDict()
        self._cache_lock = threading.Lock()
        self._locks = RunLocks()  # one per run: a cached game is never used by two threads at once

    @property
    def version(self) -> str:
        return str(balatro.__version__)

    # ------------------------------------------------------------ settings
    def random_seed(self) -> str:
        return "".join(random.SystemRandom().choice(SEED_ALPHABET) for _ in range(8))

    def check_settings(self, settings: GameSettings) -> GameSettings:
        data = load()
        deck, stake = settings.deck, settings.stake
        if settings.challenge is not None:
            try:
                ch = data.challenge(settings.challenge)
            except KeyError:
                raise InvalidGameSettings(f"unknown challenge {settings.challenge!r}") from None
            center = data.center_by_name(ch.deck.type) if ch.deck and ch.deck.type else None
            deck, stake = (center.key if center else "b_red"), 1  # challenges are played on White Stake
        else:
            deck = DECK_NAMES.get(deck.lower(), deck)
            if deck not in {c.key for c in data.P_CENTER_POOLS["Back"]}:
                raise InvalidGameSettings(f"unknown deck {settings.deck!r}")
        return GameSettings(seed=normalize_seed(settings.seed), deck=deck, stake=stake, challenge=settings.challenge,
                            game_speed=settings.game_speed, seeded=settings.seeded)

    # ------------------------------------------------------------ games
    @staticmethod
    def _new_game(s: GameSettings) -> Game:
        return Game(s.seed, deck=s.deck, stake=s.stake, challenge=s.challenge, game_speed=s.game_speed).start_run()

    def _replay(self, run: Run) -> Game:
        G = self._new_game(run.settings)
        for i, c in enumerate(run.commands):
            try:
                G.do(c.as_dict())
            except Exception as e:
                raise ReplayFailed(run.id, i, e) from e
        return G

    def _put(self, run_id: str, version: int, G: Game) -> None:
        with self._cache_lock:
            entry = self._cache.get(run_id)
            if entry is not None and entry[0] > version:
                return  # (a reader replayed an older version while the run moved on)
            self._cache[run_id] = (version, G)
            self._cache.move_to_end(run_id)
            while len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)

    @contextmanager
    def _game(self, run: Run) -> Iterator[Game]:
        """The run's game, for this thread alone while the context lasts."""
        with self._locks.hold(run.id):
            with self._cache_lock:
                entry = self._cache.get(run.id)
                if entry is not None:
                    self._cache.move_to_end(run.id)
            if entry is not None and entry[0] == run.version:
                G = entry[1]
            else:
                G = self._replay(run)
                self._put(run.id, run.version, G)
            yield G

    def start(self, run_id: str, settings: GameSettings) -> Progress:
        G = self._new_game(settings)
        self._put(run_id, 0, G)
        return presenter.progress(G)

    def forget(self, run_id: str) -> None:
        with self._cache_lock:
            self._cache.pop(run_id, None)

    # ------------------------------------------------------------ reads
    def view(self, run: Run) -> GameView:
        with self._game(run) as G:
            return presenter.game_view(run, G)

    def load(self, run: Run) -> tuple[Progress, RunStats]:
        try:
            G = self._replay(run)
        except ReplayFailed as e:
            raise IllegalAction(str(e)) from e
        self._put(run.id, run.version, G)
        return presenter.progress(G), presenter.run_stats(G)

    def run_stats(self, run: Run) -> RunStats:
        with self._game(run) as G:
            return presenter.run_stats(G)

    def legal_actions(self, run: Run) -> list[LegalAction]:
        with self._game(run) as G:
            return legal_actions(G)

    def preview_hand(self, run: Run, cards: Sequence[int]) -> HandPreview:
        with self._game(run) as G:
            hand = list(G.hand.cards) if G.hand is not None else []
            ids = {c.sort_id: i for i, c in enumerate(hand)}
            missing = [c for c in cards if c not in ids]
            if missing:
                raise IllegalAction(f"card {missing[0]} is not in the hand")
            try:
                p = G.preview_hand([ids[c] for c in cards])
            except balatro.IllegalAction as e:
                raise IllegalAction(str(e)) from e
            return HandPreview(selected=[hand[i].sort_id for i in p["selected"]], hand=p["hand"],
                               display_name=p.get("display"), level=p["level"], chips=p["chips"], mult=p["mult"],
                               scoring=[hand[i].sort_id for i in p["scoring"]], not_allowed=p["not_allowed"],
                               hidden=p["hidden"])

    @cached_property
    def _catalog(self) -> Catalog:
        return build_catalog()

    def catalog(self) -> Catalog:
        return self._catalog

    # ------------------------------------------------------------ actions
    def _play(self, G: Game, command: dict[str, Any]) -> Outcome:
        feedback = G.start_feedback()
        try:
            G.do(command)
        except balatro.IllegalAction as e:
            raise IllegalAction(str(e)) from e
        finally:
            G.stop_feedback()
        return Outcome(command=Command(command), progress=presenter.progress(G), stats=presenter.run_stats(G),
                       events=presenter.feedback_events(feedback, G), state=G)

    def apply(self, run: Run, action: PlayerAction) -> Outcome:
        with self._game(run) as G:
            copy = G.clone()
        return self._play(copy, to_command(copy, action))

    def apply_debug(self, run: Run, command: dict[str, Any]) -> Outcome:
        cmd = dict(command)
        kind = cmd.get("cmd")
        if kind not in DEBUG_COMMANDS:
            raise IllegalAction(f"debug commands are {', '.join(DEBUG_COMMANDS)}")
        with self._game(run) as G:
            known = {"add_joker": G.P_CENTERS, "add_tag": G.P_TAGS, "add_voucher": G.P_CENTERS}.get(kind)
            if known is not None and cmd.get("key") not in known:
                raise IllegalAction(f"unknown key {cmd.get('key')!r}")
            if kind == "cheat" and cmd.get("boss") is not None and cmd["boss"] not in G.P_BLINDS:
                raise IllegalAction(f"unknown blind {cmd['boss']!r}")
            copy = G.clone()
        return self._play(copy, cmd)

    def commit(self, run: Run, outcome: Outcome) -> None:
        if not isinstance(outcome.state, Game):
            raise TypeError("not an outcome of this engine")
        self._put(run.id, run.version, outcome.state)
