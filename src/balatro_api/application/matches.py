"""Multiplayer matches: the lobby, and PvP played on two runs.

A match is made by a player (the host) and joined by another with its invite
code.  When the host starts it, each player gets a run of the same seed with
the PvP rules (``GameSettings.mode`` "pvp"); they play it with the usual run
actions, and the match keeps them in step:

- **the blind select**: each player chooses to play the blind or to skip it
  (``VoteBlind``); once both have chosen, both do it, and a blind is skipped
  only if both skip it.  Until then ``select_blind``/``skip_blind`` are
  refused (``409 waiting_for_opponent``);
- **the end of a round**: a player who has finished the blind waits for the
  other to finish it too before cashing out (``cash_out`` is refused until
  then); then both lose the hit points the engine's rules say;
- **the timer**: once a player waits, the other has ``timer`` seconds; then
  the match moves them on with the game's own commands (the round is lost,
  the cash out taken, the pack skipped, the shop left, the blind played);
- the match is over when a player has no hit points left, a run ends for
  good, or a player leaves.

When a match ends, how it went is kept with it (``summary``): the players'
history (``GetMatchHistory``) and multiplayer statistics are made of them.
The players of a finished match can ask for a rematch (a new lobby with the
same settings, which the other one joins), and send each other emotes.

Nothing runs in the background: the match catches up (the timer included)
whenever it is read or one of its runs is played, which both players' games
do every second or two.  All of it happens under the match's lock, then the
runs' locks (always in that order).
"""

from __future__ import annotations

import random
from collections import deque
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import Any, Literal, cast

from balatro_api.domain import (
    BLIND_CHOICES,
    EMOTES,
    GameSettings,
    IllegalAction,
    InAnotherMatch,
    Match,
    MatchNotFound,
    MatchPlayer,
    MatchSettings,
    MatchStatus,
    Phase,
    Run,
    WaitingForOpponent,
)
from balatro_api.domain.match import CODE_ALPHABET, CODE_LENGTH

from .dto import (
    ActionResult,
    BlindChoice,
    BlindVoteView,
    CoopMatchView,
    CoopStats,
    CoopStep,
    CoopStepsView,
    EmoteName,
    EmoteView,
    MatchHistoryEntry,
    MatchHistoryView,
    MatchMode,
    MatchOpponentStats,
    MatchPlayerView,
    MatchResultView,
    MatchSettingsChange,
    MatchSettingsView,
    MatchSummaryPlayer,
    MatchSummaryView,
    MatchView,
    MultiplayerStats,
    NewMatch,
    Player,
    PvPBlindResult,
    PvPStats,
    PvPView,
    RematchView,
)
from .locks import RunLocks
from .ports import Clock, GameEngine, GameRepository, IdGenerator, MatchRecord, MatchRepository, PvPState
from .statistics import score

MATCH_PROFILE: dict[str, Any] = {"all": True}  # multiplayer runs: everything unlocked, the same pools for both
STEPS_KEPT = 64  # a coop run's last actions kept for the other player to watch
EMOTES_KEPT = 8  # a match's last emotes
EMOTE_SECONDS = 20  # an emote is in the match's view this long
EMOTE_GAP = 1.0  # seconds between two emotes of a player
HISTORY_PAGE = 20
TOP_OPPONENTS = 5


def match_lock(match_id: str) -> str:
    return "match:" + match_id


class Matches:
    """The match rules around the runs (see the module's documentation)."""

    def __init__(self, engine: GameEngine, games: GameRepository, matches: MatchRepository, locks: RunLocks,
                 clock: Clock, ids: IdGenerator) -> None:
        self.engine, self.games, self.matches = engine, games, matches
        self.locks, self.clock, self.ids = locks, clock, ids
        # (coop, in memory: one process) the cards the player whose turn it is has selected, by match:
        # (seat, card ids, sequence); a run's last actions, to watch
        self.selections: dict[str, tuple[int, list[int], int]] = {}
        self.steps: dict[str, deque[CoopStep]] = {}
        # (in memory too) a match's last emotes, and the sequence they are numbered by
        self.emotes: dict[str, deque[EmoteView]] = {}
        self.emote_seq: dict[str, int] = {}

    # ------------------------------------------------------------ loading
    def runs(self, match: Match) -> list[Run]:
        return [self.games.get(p.run_id) for p in match.players if p.run_id is not None]

    def records(self, match: Match) -> list[MatchRecord]:
        return [self.engine.match_record(r) for r in self.runs(match)]

    def save(self, match: Match) -> None:
        version = match.version
        self.matches.save_match(match, version)
        match.version = version + 1

    def new_code(self) -> str:
        rnd = random.SystemRandom()
        for _ in range(20):
            code = "".join(rnd.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
            try:
                self.matches.match_by_code(code)
            except MatchNotFound:
                return code
        raise RuntimeError("no free invite code")

    # ------------------------------------------------------------ the server's moves
    def play_for(self, run: Run, command: dict[str, Any]) -> None:
        """A command the match plays on a player's run (as an action of theirs: on a copy, saved, then kept)."""
        with self.locks.hold(run.id):
            run = self.games.get(run.id)
            run.check_playable()
            outcome = self.engine.apply_command(run, command)
            version = run.version
            run.record(outcome.command, outcome.progress, self.clock.now(), stats=outcome.stats)
            self.games.save(run, expected_version=version)
            self.engine.commit(run, outcome)

    # ------------------------------------------------------------ PvP
    @staticmethod
    def waiting_point(match: Match, seat: int, records: list[MatchRecord]) -> str | None:
        """What the player waits for the other one to do, if anything."""
        mine, theirs = records[seat], records[1 - seat]
        n = len(mine.blinds)
        if mine.phase is Phase.ROUND_EVAL and n > len(theirs.blinds):
            return f"round:{n - 1}"  # they finished blind n-1: the other one still plays it
        if mine.phase is Phase.BLIND_SELECT:
            votes = match.votes.get(n, {})
            if seat in votes and (1 - seat) not in votes:
                return f"vote:{n}"
        return None

    def pvp_state(self, records: list[MatchRecord]) -> PvPState:
        return self.engine.pvp_state([r.blinds for r in records], [r.game_over for r in records])

    # ------------------------------------------------------------ coop
    def record_step(self, run_id: str, step: CoopStep) -> None:
        self.steps.setdefault(run_id, deque(maxlen=STEPS_KEPT)).append(step)

    def steps_since(self, run_id: str, version: int, current: int) -> CoopStepsView:
        steps = [st for st in self.steps.get(run_id, ()) if st.version >= version]
        complete = version >= current or (bool(steps) and steps[0].version == version
                                          and len(steps) == current - version)
        return CoopStepsView(steps=steps if complete else [], complete=complete)

    def coop_view(self, match: Match, seat: int) -> CoopMatchView | None:
        run_id = match.players[seat].run_id
        state = self.engine.coop_state(self.games.get(run_id)) if run_id else None
        if state is None:
            return None
        sel_seat, cards, seq = self.selections.get(match.id, (-1, [], 0))
        turn = int(state["turn"])
        return CoopMatchView(turn=turn, your_turn=turn == seat, selection=cards if sel_seat == turn else [],
                             selection_seq=seq, over=bool(state["over"]))

    def refresh(self, match: Match) -> tuple[list[MatchRecord], PvPState | None]:
        """Catch up (the caller holds the match's lock): who waits since when, the timer, the end."""
        if match.status is MatchStatus.PLAYING and match.mode == "coop":
            run_id = match.players[0].run_id
            coop = self.engine.coop_state(self.games.get(run_id)) if run_id else None
            if coop is not None and coop["over"]:
                match.finish(None, "game_over", self.clock.now())
                self.summarize(match)
                self.save(match)
            return [], None
        if match.status is not MatchStatus.PLAYING or match.mode != "pvp":
            return [], None
        changed = False
        records = self.records(match)
        state = self.pvp_state(records)
        for _ in range(4):
            if state.over:
                match.finish(state.winner, "game_over" if any(r.game_over for r in records) else "hp",
                             self.clock.now())
                self.summarize(match, records, state)
                changed = True
                break
            now = self.clock.now()
            for seat in range(len(match.players)):
                changed |= match.set_wait(seat, self.waiting_point(match, seat, records), now)
            late = [(seat, w) for seat, w in match.waits.items()
                    if now >= w.since + timedelta(seconds=match.settings.timer) and (1 - seat) not in match.waits]
            if not late:
                break
            seat, wait = late[0]
            self.move_on(match, 1 - seat, wait.point)
            changed = True
            records = self.records(match)
            state = self.pvp_state(records)
        if changed:
            self.save(match)
        return records, state

    def move_on(self, match: Match, seat: int, point: str) -> None:
        """The timer ran out for ``seat``: play their run up to ``point`` (where the other player waits)."""
        kind, _, index = point.partition(":")
        target = int(index)
        run_id = match.players[seat].run_id
        assert run_id is not None
        for _ in range(12):
            run = self.games.get(run_id)
            rec = self.engine.match_record(run)
            if rec.game_over:
                return
            if kind == "round" and len(rec.blinds) > target:
                return
            if kind == "vote" and seat in match.votes.get(target, {}):
                return
            if rec.phase is Phase.BLIND_SELECT:
                n = len(rec.blinds)
                decision = match.decision(n)
                if decision is None:
                    if seat in match.votes.get(n, {}):
                        return
                    match.vote(seat, n, "select", self.clock.now())
                    continue
                self.play_for(run, {"cmd": "skip_blind" if decision == "skip" else "select_blind"})
                continue
            command = self.engine.timeout_command(run)
            if command is None:
                return
            self.play_for(run, command)

    def check_action(self, match: Match, seat: int, action: str, records: list[MatchRecord]) -> None:
        """The match's gates on a player's own actions."""
        if match.status is not MatchStatus.PLAYING or match.mode != "pvp" or len(records) < 2:
            return
        mine, theirs = records[seat], records[1 - seat]
        if action in ("select_blind", "skip_blind"):
            decision = match.decision(len(mine.blinds))
            if decision is None:
                raise WaitingForOpponent("both players choose first whether to play or skip the blind")
            if (decision == "skip") != (action == "skip_blind"):
                raise IllegalAction(f"both players chose to {decision} this blind")
        elif action == "cash_out" and len(theirs.blinds) < len(mine.blinds):
            raise WaitingForOpponent("the other player hasn't finished the round yet")

    def play(self, player: Player, run: Run, action: str, act: Callable[[], ActionResult]) -> ActionResult:
        """A player's action on their run of a match: the match's gates, then the action, then the match catches up."""
        assert run.match_id is not None
        with self.locks.hold(match_lock(run.match_id)):
            match = self.matches.get_match(run.match_id)
            seat = match.member(player.id)
            records, _ = self.refresh(match)
            self.check_action(match, seat, action, records)
            result = act()
            self.refresh(match)
            return result

    # ------------------------------------------------------------ views
    def view(self, match: Match, player_id: str, records: list[MatchRecord] | None = None,
             state: PvPState | None = None) -> MatchView:
        seat = match.member(player_id)
        me = match.players[seat]
        run_version = None
        if me.run_id is not None:
            run_version = records[seat].version if records else self.games.get(me.run_id).version
        s = match.settings
        result = None
        if match.status is MatchStatus.FINISHED:
            result = MatchResultView(winner=match.winner, you_won=match.winner == seat, reason=match.result or "")
        pvp = None
        if match.mode == "pvp" and match.status is not MatchStatus.LOBBY:
            if not records:
                records = self.records(match)
            if state is None:
                state = self.pvp_state(records)
            pvp = self.pvp_view(match, seat, records, state)
        coop = self.coop_view(match, seat) if match.mode == "coop" and match.status is not MatchStatus.LOBBY else None
        rematch = None
        if match.rematch_id is not None:
            nxt = self.matches.get_match(match.rematch_id)
            rematch = RematchView(match_id=nxt.id, code=nxt.code, by_you=nxt.host == player_id,
                                  open=nxt.status is MatchStatus.LOBBY)
        return MatchView(
            id=match.id, version=match.version, code=match.code, mode=cast(MatchMode, match.mode),
            status=match.status.value, seat=seat, host=match.host == player_id,
            settings=MatchSettingsView(deck=s.deck, stake=s.stake, seed=s.seed, timer=s.timer),
            players=[MatchPlayerView(seat=i, name=p.name, you=p.id == player_id, host=p.id == match.host,
                                     left=p.left) for i, p in enumerate(match.players)],
            run_id=me.run_id, run_version=run_version, pvp=pvp, result=result, server_time=self.clock.now(),
            coop=coop, summary=summary_view(match), rematch=rematch, emotes=self.recent_emotes(match.id))

    def pvp_view(self, match: Match, seat: int, records: list[MatchRecord], state: PvPState) -> PvPView:
        other = 1 - seat
        mine = records[seat]
        n = len(mine.blinds)
        vote = None
        if mine.phase is Phase.BLIND_SELECT and match.status is MatchStatus.PLAYING:
            votes = match.votes.get(n, {})
            yours, theirs = votes.get(seat), votes.get(other)
            vote = BlindVoteView(index=n, yours=cast(BlindChoice, yours.choice) if yours else None,
                                 theirs=cast(BlindChoice, theirs.choice) if theirs else None,
                                 decision=cast(BlindChoice | None, match.decision(n)))

        def kind(point: str | None) -> Literal["round", "vote"] | None:
            return cast(Literal["round", "vote"], point.partition(":")[0]) if point else None

        waits = match.waits
        deadline = None
        for w in waits.values():
            deadline = w.since + timedelta(seconds=match.settings.timer)
        rounds = [PvPBlindResult(
            index=r["index"], ante=r.get("ante") or 0, slot=r.get("slot"),
            chips=[score(float(e.get("chips") or 0)) for e in r["players"]],
            target=[score(float(e.get("target") or 0)) for e in r["players"]],
            lost=[bool(e.get("lost")) for e in r["players"]], skipped=[bool(e.get("skipped")) for e in r["players"]],
            damage=list(r["damage"]), hp=list(r["hp"])) for r in state.rounds]
        opponent_run = match.players[other].run_id
        return PvPView(
            start_hp=state.start_hp, safe_antes=state.safe_antes, loss_damage=state.loss_damage, hp=state.hp,
            blind_index=n, rounds=rounds, vote=vote,
            waiting=kind(waits[seat].point) if seat in waits else None,
            opponent_waiting=kind(waits[other].point) if other in waits else None,
            deadline=deadline,
            can_cash_out=match.status is not MatchStatus.PLAYING or len(records[other].blinds) >= n,
            opponent=self.engine.opponent_view(self.games.get(opponent_run)) if opponent_run else None)


    # ------------------------------------------------------------ the end
    def summarize(self, match: Match, records: list[MatchRecord] | None = None, state: PvPState | None = None) -> None:
        """How the match went, kept with it once it is over (the players' history and statistics)."""
        if match.summary is not None or not match.played:
            return
        runs = [self.games.get(p.run_id) if p.run_id else None for p in match.players]
        players: list[dict[str, Any]] = []
        if match.mode == "pvp":
            records = records or self.records(match)
            if len(records) < len(match.players):
                return
            state = state or self.pvp_state(records)
            for seat, p in enumerate(match.players):
                other = 1 - seat
                dealt = [int(r["damage"][other]) for r in state.rounds if not r["players"][other].get("lost")]
                won = sum(1 for r in state.rounds if not r["players"][seat].get("skipped")
                          and chips_of(r, seat) > chips_of(r, other))
                run = runs[seat]
                players.append({
                    "seat": seat, "name": p.name, "best_hand": score(run.stats.best_hand) if run else 0,
                    "hp": state.hp[seat], "damage_dealt": sum(dealt),
                    "damage_taken": sum(int(r["damage"][seat]) for r in state.rounds),
                    "biggest_hit": max(dealt, default=0), "rounds_won": won,
                    "rounds_lost": sum(1 for r in state.rounds if r["players"][seat].get("lost"))})
            match.summary = {"ante": max((r.progress.ante for r in runs if r), default=0),
                             "rounds": len(state.rounds), "players": players}
            return
        run = runs[0]
        if run is None:
            return
        coop = self.engine.coop_state(run) or {}
        stats = coop.get("stats") or []
        for seat, p in enumerate(match.players):
            st = stats[seat] if seat < len(stats) else {}
            players.append({
                "seat": seat, "name": p.name, "best_hand": score(float(st.get("best_hand") or 0)),
                "best_hand_name": st.get("best_hand_name"), "hands": int(st.get("hands") or 0),
                "chips": score(float(st.get("chips") or 0)), "discards": int(st.get("discards") or 0)})
        match.summary = {"ante": run.progress.ante, "rounds": run.progress.round, "run_won": run.progress.won,
                         "players": players}

    def history_entry(self, match: Match, player_id: str) -> MatchHistoryEntry:
        seat = match.member(player_id)
        s = match.settings
        return MatchHistoryEntry(
            id=match.id, mode=cast(MatchMode, match.mode),
            settings=MatchSettingsView(deck=s.deck, stake=s.stake, seed=s.seed, timer=s.timer), seed=match.seed,
            created_at=match.created_at, finished_at=match.finished_at, seat=seat,
            players=[MatchPlayerView(seat=i, name=p.name, you=p.id == player_id, host=p.id == match.host,
                                     left=p.left) for i, p in enumerate(match.players)],
            result=MatchResultView(winner=match.winner, you_won=match.winner == seat, reason=match.result or ""),
            summary=summary_view(match), runs=[p.run_id for p in match.players])

    # ------------------------------------------------------------ emotes
    def emote(self, match: Match, seat: int, emote: str) -> None:
        now = self.clock.now()
        kept = self.emotes.setdefault(match.id, deque(maxlen=EMOTES_KEPT))
        last = next((e for e in reversed(kept) if e.seat == seat), None)
        if last is not None and (now - last.at).total_seconds() < EMOTE_GAP:
            return  # (too many at once: the extra ones are dropped)
        seq = self.emote_seq.get(match.id, 0) + 1
        self.emote_seq[match.id] = seq
        kept.append(EmoteView(seq=seq, seat=seat, emote=cast(EmoteName, emote), at=now))

    def recent_emotes(self, match_id: str) -> list[EmoteView]:
        now = self.clock.now()
        return [e for e in self.emotes.get(match_id, ()) if (now - e.at).total_seconds() <= EMOTE_SECONDS]


def chips_of(blind: dict[str, Any], seat: int) -> float:
    """A player's chips at a blind of the PvP rounds."""
    return float(blind["players"][seat].get("chips") or 0)


def summary_view(match: Match) -> MatchSummaryView | None:
    s = match.summary
    if not s:
        return None
    return MatchSummaryView(ante=int(s.get("ante") or 0), rounds=int(s.get("rounds") or 0), run_won=s.get("run_won"),
                            players=[MatchSummaryPlayer(**p) for p in s.get("players") or []])


def multiplayer_stats(matches: Sequence[Match], player_id: str) -> MultiplayerStats:
    """A player's PvP and coop numbers, from their finished matches (any order)."""
    pvp: dict[str, Any] = {k: 0 for k in ("played", "won", "lost", "drawn", "gave_up", "opponent_left", "streak",
                                          "best_streak", "damage_dealt", "damage_taken", "biggest_hit", "best_ante")}
    coop: dict[str, Any] = {"played": 0, "runs_won": 0, "best_ante": 0, "best_round": 0, "hands": 0, "chips": 0.0,
                            "best_hand": 0.0, "best_hand_name": None}
    rivals: dict[str, dict[str, Any]] = {}
    partners: dict[str, dict[str, Any]] = {}

    def num(x: Any) -> float:
        try:
            return float(x)
        except (TypeError, ValueError):
            return 0.0

    for m in sorted(matches, key=lambda m: m.finished_at or m.updated_at):
        seat = m.seat_of(player_id)
        if seat is None or not m.played:
            continue
        others = [p for p in m.players if p.id != player_id]
        summary = m.summary or {}
        me: dict[str, Any] = next((p for p in summary.get("players") or [] if p.get("seat") == seat), {})
        ante = int(summary.get("ante") or 0)
        if m.mode == "pvp":
            pvp["played"] += 1
            if m.winner is None:
                pvp["drawn"] += 1
            elif m.winner == seat:
                pvp["won"] += 1
                pvp["opponent_left"] += m.result == "left"
            else:
                pvp["lost"] += 1
                pvp["gave_up"] += m.result == "left" and m.players[seat].left
            pvp["streak"] = pvp["streak"] + 1 if m.winner == seat else 0
            pvp["best_streak"] = max(pvp["best_streak"], pvp["streak"])
            pvp["damage_dealt"] += int(me.get("damage_dealt") or 0)
            pvp["damage_taken"] += int(me.get("damage_taken") or 0)
            pvp["biggest_hit"] = max(pvp["biggest_hit"], int(me.get("biggest_hit") or 0))
            pvp["best_ante"] = max(pvp["best_ante"], ante)
            for o in others:
                r = rivals.setdefault(o.id, {"name": o.name, "played": 0, "won": 0, "lost": 0})
                r["name"] = o.name or r["name"]
                r["played"] += 1
                r["won"] += m.winner == seat
                r["lost"] += m.winner is not None and m.winner != seat
        else:
            coop["played"] += 1
            coop["runs_won"] += bool(summary.get("run_won"))
            coop["best_ante"] = max(coop["best_ante"], ante)
            coop["best_round"] = max(coop["best_round"], int(summary.get("rounds") or 0))
            coop["hands"] += int(me.get("hands") or 0)
            coop["chips"] += num(me.get("chips"))
            if num(me.get("best_hand")) > coop["best_hand"]:
                coop["best_hand"], coop["best_hand_name"] = num(me.get("best_hand")), me.get("best_hand_name")
            for o in others:
                r = partners.setdefault(o.id, {"name": o.name, "played": 0, "best_ante": 0})
                r["name"] = o.name or r["name"]
                r["played"] += 1
                r["best_ante"] = max(r["best_ante"], ante)

    def top(d: dict[str, dict[str, Any]]) -> list[MatchOpponentStats]:
        rows = sorted(d.values(), key=lambda r: -r["played"])[:TOP_OPPONENTS]
        return [MatchOpponentStats(**r) for r in rows]

    coop["chips"], coop["best_hand"] = score(coop["chips"]), score(coop["best_hand"])
    return MultiplayerStats(pvp=PvPStats(**pvp), coop=CoopStats(**coop), rivals=top(rivals), partners=top(partners))


def leave_lobbies(matches: Matches, player: Player) -> None:
    """Before making or joining a match: out of the lobby the player is in; playing one is refused."""
    current = matches.matches.current_match(player.id)
    if current is None:
        return
    if current.status is MatchStatus.PLAYING:
        raise InAnotherMatch(current.id)
    with matches.locks.hold(match_lock(current.id)):
        current = matches.matches.get_match(current.id)
        if current.status is MatchStatus.LOBBY:
            current.leave(player.id, matches.clock.now())
            matches.save(current)


class CreateMatch:
    def __init__(self, matches: Matches) -> None:
        self.m = matches

    def __call__(self, player: Player, request: NewMatch) -> MatchView:
        m = self.m
        settings = MatchSettings(deck=request.deck, stake=request.stake, seed=request.seed, timer=request.timer)
        m.engine.check_settings(GameSettings(seed=settings.seed or "A", deck=settings.deck, stake=settings.stake))
        leave_lobbies(m, player)
        now = m.clock.now()
        match = Match(id=m.ids.new_id(), code=m.new_code(), mode=request.mode, host=player.id, created_at=now,
                      updated_at=now, settings=settings,
                      players=[MatchPlayer(id=player.id, name=player.name, game_speed=request.game_speed)])
        m.matches.add_match(match)
        return m.view(match, player.id)


class JoinMatch:
    def __init__(self, matches: Matches) -> None:
        self.m = matches

    def __call__(self, player: Player, code: str, game_speed: float = 1.0) -> MatchView:
        m = self.m
        found = m.matches.match_by_code(code.strip().upper())
        if found.seat_of(player.id) is None:
            leave_lobbies(m, player)
        with m.locks.hold(match_lock(found.id)):
            match = m.matches.get_match(found.id)
            match.join(MatchPlayer(id=player.id, name=player.name, game_speed=game_speed), m.clock.now())
            m.save(match)
            return m.view(match, player.id)


class GetMatch:
    def __init__(self, matches: Matches) -> None:
        self.m = matches

    def __call__(self, player: Player, match_id: str) -> MatchView:
        m = self.m
        with m.locks.hold(match_lock(match_id)):
            match = m.matches.get_match(match_id)
            match.member(player.id)
            records, state = m.refresh(match)
            return m.view(match, player.id, records, state)


class CurrentMatch:
    """The player's match not finished yet (to go back to it), if any."""

    def __init__(self, matches: Matches) -> None:
        self.m = matches

    def __call__(self, player: Player) -> MatchView | None:
        current = self.m.matches.current_match(player.id)
        if current is None:
            return None
        return GetMatch(self.m)(player, current.id)


class ChangeMatchSettings:
    def __init__(self, matches: Matches) -> None:
        self.m = matches

    def __call__(self, player: Player, match_id: str, change: MatchSettingsChange) -> MatchView:
        m = self.m
        settings = MatchSettings(deck=change.deck, stake=change.stake, seed=change.seed, timer=change.timer)
        m.engine.check_settings(GameSettings(seed=settings.seed or "A", deck=settings.deck, stake=settings.stake))
        with m.locks.hold(match_lock(match_id)):
            match = m.matches.get_match(match_id)
            match.member(player.id)
            match.check_host(player.id)
            match.change_settings(settings, m.clock.now())
            m.save(match)
            return m.view(match, player.id)


class StartMatch:
    """The host starts the match: a run for each player, the same seed, deck and stake (everything unlocked)."""

    def __init__(self, matches: Matches) -> None:
        self.m = matches

    def __call__(self, player: Player, match_id: str) -> MatchView:
        m = self.m
        with m.locks.hold(match_lock(match_id)):
            match = m.matches.get_match(match_id)
            match.member(player.id)
            match.check_host(player.id)
            if match.status is not MatchStatus.LOBBY:
                return m.view(match, player.id)
            if len(match.players) < 2:
                raise IllegalAction("the match needs two players")
            s = match.settings
            seed = s.seed or m.engine.random_seed()
            now = m.clock.now()
            run_ids: list[str] = []
            # PvP: a run each; coop: one run for both (its owner the host; the other player plays it too)
            for p in match.players if match.mode == "pvp" else match.players[:1]:
                settings = m.engine.check_settings(GameSettings(
                    seed=seed, deck=s.deck, stake=s.stake, game_speed=p.game_speed, seeded=True, mode=match.mode))
                run_id = m.ids.new_id()
                progress = m.engine.start(run_id, settings, MATCH_PROFILE)
                run = Run(id=run_id, settings=settings, engine_version=m.engine.version, progress=progress,
                          created_at=now, updated_at=now, owner=p.id, owner_name=p.name, match_id=match.id,
                          start_profile=dict(MATCH_PROFILE))
                run.stats = m.engine.run_stats(run)
                m.games.add(run)
                run_ids.append(run_id)
            if match.mode == "coop":
                run_ids = run_ids * len(match.players)
            match.start(settings.seed, run_ids, now)
            m.save(match)
            return m.view(match, player.id)


class VoteBlind:
    """Play or skip the blind on deck (PvP): it happens once both players have chosen."""

    def __init__(self, matches: Matches) -> None:
        self.m = matches

    def __call__(self, player: Player, match_id: str, choice: str) -> MatchView:
        m = self.m
        if choice not in BLIND_CHOICES:
            raise IllegalAction(f"choose {' or '.join(BLIND_CHOICES)}")
        with m.locks.hold(match_lock(match_id)):
            match = m.matches.get_match(match_id)
            seat = match.member(player.id)
            records, _ = m.refresh(match)
            if match.status is not MatchStatus.PLAYING:
                raise IllegalAction("the match is over")
            mine = records[seat]
            if mine.phase is not Phase.BLIND_SELECT:
                raise IllegalAction("not at the blind select")
            if choice == "skip" and not mine.can_skip:
                raise IllegalAction("this blind can't be skipped")
            match.vote(seat, len(mine.blinds), choice, m.clock.now())
            m.save(match)
            records, state = m.refresh(match)
            return m.view(match, player.id, records, state)


class LeaveMatch:
    """Leave the lobby (the host closes it), or give the match up (the other player wins)."""

    def __init__(self, matches: Matches) -> None:
        self.m = matches

    def __call__(self, player: Player, match_id: str) -> None:
        m = self.m
        with m.locks.hold(match_lock(match_id)):
            match = m.matches.get_match(match_id)
            match.member(player.id)
            if match.active:
                match.leave(player.id, m.clock.now())
                m.summarize(match)
                m.save(match)




class SetSelection:
    """Coop: the cards the player whose turn it is has selected, for the other player to watch (not saved)."""

    def __init__(self, matches: Matches) -> None:
        self.m = matches

    def __call__(self, player: Player, match_id: str, cards: list[int]) -> None:
        m = self.m
        match = m.matches.get_match(match_id)
        seat = match.member(player.id)
        if match.mode != "coop" or match.status is not MatchStatus.PLAYING:
            raise IllegalAction("not a coop match being played")
        _, _, seq = m.selections.get(match.id, (-1, [], 0))
        m.selections[match.id] = (seat, list(cards)[:8], seq + 1)


class GetSteps:
    """Coop: the run's actions since a version, with what the game showed (the other player's, to watch them)."""

    def __init__(self, matches: Matches) -> None:
        self.m = matches

    def __call__(self, player: Player, match_id: str, since: int) -> CoopStepsView:
        m = self.m
        match = m.matches.get_match(match_id)
        seat = match.member(player.id)
        run_id = match.players[seat].run_id
        if match.mode != "coop" or run_id is None:
            raise IllegalAction("not a coop match")
        return m.steps_since(run_id, since, m.games.get(run_id).version)


__all__ = ["ChangeMatchSettings", "CreateMatch", "CurrentMatch", "GetMatch", "GetSteps", "JoinMatch", "LeaveMatch",
           "Matches", "SetSelection", "StartMatch", "VoteBlind", "match_lock"]


class Rematch:
    """After a match: play again.  The first player to ask makes a new lobby with the same mode and settings
    (their host); the other one, asking too, joins it."""

    def __init__(self, matches: Matches) -> None:
        self.m = matches

    def __call__(self, player: Player, match_id: str) -> MatchView:
        m = self.m
        with m.locks.hold(match_lock(match_id)):
            old = m.matches.get_match(match_id)
            seat = old.member(player.id)
            if not old.played:
                raise IllegalAction("the match isn't over")
            if old.rematch_id is not None:
                nxt = m.matches.get_match(old.rematch_id)
                if nxt.seat_of(player.id) is not None:
                    return m.view(nxt, player.id)
                if nxt.status is MatchStatus.LOBBY:
                    return JoinMatch(m)(player, nxt.code, old.players[seat].game_speed)
            leave_lobbies(m, player)
            now = m.clock.now()
            nxt = Match(id=m.ids.new_id(), code=m.new_code(), mode=old.mode, host=player.id, created_at=now,
                        updated_at=now, settings=old.settings,
                        players=[MatchPlayer(id=player.id, name=player.name,
                                             game_speed=old.players[seat].game_speed)])
            m.matches.add_match(nxt)
            old.rematch_id = nxt.id
            m.save(old)
            return m.view(nxt, player.id)


class KickPlayer:
    """The host sends a player away from the lobby (they can't join it again)."""

    def __init__(self, matches: Matches) -> None:
        self.m = matches

    def __call__(self, player: Player, match_id: str, seat: int) -> MatchView:
        m = self.m
        with m.locks.hold(match_lock(match_id)):
            match = m.matches.get_match(match_id)
            match.member(player.id)
            match.kick(player.id, seat, m.clock.now())
            m.save(match)
            return m.view(match, player.id)


class SendEmote:
    """A quick message to the other player (kept in memory a few seconds: the match's view shows it)."""

    def __init__(self, matches: Matches) -> None:
        self.m = matches

    def __call__(self, player: Player, match_id: str, emote: str) -> None:
        if emote not in EMOTES:
            raise IllegalAction(f"an emote is one of {', '.join(EMOTES)}")
        m = self.m
        match = m.matches.get_match(match_id)
        seat = match.member(player.id)
        if match.status is MatchStatus.FINISHED and match.result == "closed":
            raise IllegalAction("the lobby is closed")
        m.emote(match, seat, emote)


class GetMatchHistory:
    """The caller's finished matches, the latest first."""

    def __init__(self, matches: Matches) -> None:
        self.m = matches

    def __call__(self, player: Player, limit: int = HISTORY_PAGE, before: datetime | None = None) -> MatchHistoryView:
        found = self.m.matches.finished_matches(player.id, limit, before)
        return MatchHistoryView(matches=[self.m.history_entry(x, player.id) for x in found],
                                next_before=found[-1].updated_at if len(found) == limit else None)


class GetMultiplayerStats:
    def __init__(self, matches: Matches) -> None:
        self.m = matches

    def __call__(self, player: Player) -> MultiplayerStats:
        return multiplayer_stats(self.m.matches.finished_matches(player.id), player.id)
