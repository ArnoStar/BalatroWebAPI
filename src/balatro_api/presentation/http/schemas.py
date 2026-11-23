"""Request bodies.  (Responses are the application's dataclasses.)"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from balatro_api.application.dto import (
    CreativeCommand,
    EmoteName,
    ImportedRun,
    MatchSettingsChange,
    ModChoice,
    NewGame,
    NewMatch,
    PlayerAction,
    PlayerSettings,
)

Version = Annotated[int | None, Field(
    default=None, ge=0,
    description="The game version the action is meant for (GameView.version). If the game has moved on, the "
                "action is refused with 409 version_conflict instead of being applied to another state.")]
CardId = Annotated[int, Field(description="A card id (CardView.id)")]


class ModChoiceRequest(BaseModel):
    """A mod to play the run with: ``package`` (the mod's JSON, e.g. from a file; the server checks and keeps
    it), or a published mod's ``id`` (its latest version, or ``version``), or a kept package's ``hash``."""

    model_config = ConfigDict(extra="forbid")

    package: dict[str, Any] | None = None
    id: str | None = Field(None, max_length=32)
    version: str | None = Field(None, max_length=20)
    hash: str | None = Field(None, pattern=r"^[0-9a-f]{64}$")

    def to_dto(self) -> ModChoice:
        return ModChoice(package=self.package, id=self.id, version=self.version, hash=self.hash)


class NewGameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed: str | None = Field(None, pattern=r"^[A-Za-z0-9]{1,8}$",
                             description="1 to 8 letters or digits; none for a random seed")
    deck: str = Field("b_red", description="A deck key from the catalog (b_red, b_blue ...) or its short name (red)")
    stake: int = Field(1, ge=1, le=8, description="1 White ... 8 Gold")
    challenge: str | None = Field(None, description="A challenge id; it sets the deck, and the stake to White")
    game_speed: float = Field(
        1, json_schema_extra={"enum": [0.5, 1, 2, 4]},
        description="The game's speed setting: 0.5, 1, 2 or 4. It decides when animated effects land, which settles "
                    "a few timing races in the game; the default matches the game's default.")
    mods: list[ModChoiceRequest] = Field(
        default_factory=list, max_length=16,
        description="Content mods to play with (a mod's deck is then a valid deck). The run doesn't count for "
                    "statistics and unlocks nothing. An invalid package is 422 invalid_mod, with its errors.")

    def to_dto(self) -> NewGame:
        return NewGame(seed=self.seed, deck=self.deck, stake=self.stake, challenge=self.challenge,
                       game_speed=float(self.game_speed), mods=tuple(m.to_dto() for m in self.mods))


PointerEntry = Annotated[list[int | float | Annotated[str, Field(max_length=16)]], Field(min_length=2, max_length=24)]


class PointerTrace(BaseModel):
    """The player's pointer before an action, kept to show it when the run is watched again: what
    the game recorded since the previous action, in its own format (entries of numbers and short
    strings). Changes nothing in the run."""

    model_config = ConfigDict(extra="forbid")
    v: Literal[1] = 1
    e: list[PointerEntry] = Field(default_factory=list, max_length=4000)


class _Action(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: Version = None
    pointer: PointerTrace | None = Field(None, description="The player's pointer before the action (for watching "
                                                           "the run again); it changes nothing in the game")

    def to_dto(self) -> PlayerAction:
        fields = self.model_dump(exclude={"expected_version", "pointer"})
        for k in ("cards", "targets"):
            if fields.get(k) is not None:
                fields[k] = tuple(fields[k])
        return PlayerAction(**fields)


class SelectBlind(_Action):
    """Play the blind on deck."""
    type: Literal["select_blind"]


class SkipBlind(_Action):
    """Skip the Small or Big blind and take its tag."""
    type: Literal["skip_blind"]


class RerollBoss(_Action):
    """Reroll the boss blind ($10; needs Director's Cut or Retcon)."""
    type: Literal["reroll_boss"]


class Play(_Action):
    """Play these hand cards (a forced card is played too)."""
    type: Literal["play"]
    cards: list[CardId]


class Discard(_Action):
    type: Literal["discard"]
    cards: list[CardId]


class Sort(_Action):
    """The hand's sort buttons."""
    type: Literal["sort"]
    mode: Literal["rank", "suit"] = "rank"


class CashOut(_Action):
    type: Literal["cash_out"]


class Buy(_Action):
    """Buy a shop card, redeem the voucher or open a booster pack.
    ``use``: buy a consumable and use it at once."""
    type: Literal["buy"]
    card: CardId
    use: bool = False


class Reroll(_Action):
    type: Literal["reroll"]


class EndShop(_Action):
    """Leave the shop (Next Round)."""
    type: Literal["end_shop"]


class Use(_Action):
    """Use a consumable; ``targets`` are the hand cards it acts on."""
    type: Literal["use"]
    card: CardId
    targets: list[CardId] | None = None


class Sell(_Action):
    type: Literal["sell"]
    card: CardId


class Move(_Action):
    """Drag a joker, consumable or hand card to another position."""
    type: Literal["move"]
    card: CardId
    to: int = Field(ge=0, description="The new position, 0 = leftmost")


class Pick(_Action):
    """Take or use a card from the open booster pack; ``targets``: hand cards."""
    type: Literal["pick"]
    card: CardId
    targets: list[CardId] | None = None


class SkipPack(_Action):
    type: Literal["skip_pack"]


class Continue(_Action):
    """The player continues this run from the main menu (as the game's Continue: it can unlock
    Throwback). Recorded only when it changes something; otherwise the game is returned as it is."""
    type: Literal["continue"]


ActionRequest = Annotated[
    SelectBlind | SkipBlind | RerollBoss | Play | Discard | Sort | CashOut | Buy | Reroll | EndShop | Use | Sell
    | Move | Pick | SkipPack | Continue,
    Field(discriminator="type"),
]


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cards: list[CardId] = Field(description="The hand cards the player has selected")


class DebugRequest(BaseModel):
    """A test helper, in the engine's format: ``{"cmd": "cheat", "dollars": 100}``,
    ``{"cmd": "cheat", "boss": "bl_hook"}``, ``{"cmd": "cheat", "ante": 8}``,
    ``{"cmd": "cheat", "win": true}``, ``{"cmd": "add_joker", "key": "j_blueprint", "edition": "negative"}``,
    ``{"cmd": "add_tag", "key": "tag_charm"}``, ``{"cmd": "add_voucher", "key": "v_retcon"}``."""

    model_config = ConfigDict(extra="forbid")
    command: dict[str, Any]
    expected_version: Version = None


class ImportSettings(BaseModel):
    seed: str = Field(pattern=r"^[A-Za-z0-9]{1,8}$")
    deck: str = "b_red"
    stake: int = Field(1, ge=1, le=8)
    challenge: str | None = None
    game_speed: float = Field(1, json_schema_extra={"enum": [0.5, 1, 2, 4]})
    seeded: bool = True
    mods: list[dict[str, Any]] = Field(default_factory=list, max_length=16)
    mode: str | None = Field(None, description="a multiplayer run's rules (pvp, coop): its commands replay by them")


class ImportGameRequest(BaseModel):
    """A run's history (``GET /games/{id}/history``: its settings and
    commands), to rebuild it as a new run of the caller's."""

    model_config = ConfigDict(extra="ignore")

    settings: ImportSettings
    commands: list[dict[str, Any]] = Field(default_factory=list, max_length=20000,
                                           description="engine commands, as in a history (indices into the areas)")
    start_profile: dict[str, Any] | None = Field(None, description="the history's start_profile")
    mod_packages: dict[str, dict[str, Any]] | None = Field(None, description="the history's mod_packages")

    def to_dto(self) -> ImportedRun:
        s = self.settings
        # (a history from before progress was kept has no start profile: it rebuilds as a seeded run did)
        return ImportedRun(seed=s.seed, deck=s.deck, stake=s.stake, challenge=s.challenge,
                           game_speed=float(s.game_speed), commands=tuple(self.commands),
                           seeded=s.seeded if self.start_profile is not None else True,
                           start_profile=self.start_profile, mods=tuple(s.mods), mod_packages=self.mod_packages,
                           mode=s.mode)


class CreativeRequest(BaseModel):
    """A creative mode change (a run played with a creative mod, its ``settings.mods`` say so). ``op``:

    - ``set``: ``what`` (money, hands, discards, hand_size, joker_slots, consumable_slots, ante, round_chips,
      reroll_cost, interest_cap) to ``value``;
    - ``level``: the poker ``hand``'s level to ``value``;
    - ``add``: the card ``key`` (a joker or consumable, with ``edition``, ``eternal``, ``perishable``,
      ``rental``; a voucher, redeemed; a tag) — the game's or a mod's;
    - ``add_card``: a playing card (``rank``, ``suit``, ``enhancement``, ``edition``, ``seal``) ``to`` the
      hand or the deck;
    - ``edit``: the ``card`` (a joker, consumable or hand card): ``edition`` (``none`` removes it), ``seal``,
      ``enhancement``, ``rank`` (or ``up``/``down``), ``suit``, ``eternal``, ``perishable``, ``rental``;
    - ``remove``: the ``card``; ``boss``: the ante's boss is ``key`` (at the blind select); ``win``: the round
      is won now.

    Each goes through the game's own functions, and is recorded like an action (the run replays with it)."""

    model_config = ConfigDict(extra="forbid")

    op: Literal["set", "level", "add", "add_card", "edit", "remove", "boss", "win"]
    what: Literal["money", "hands", "discards", "hand_size", "joker_slots", "consumable_slots", "ante",
                  "round_chips", "reroll_cost", "interest_cap"] | None = None
    value: float | None = None
    hand: str | None = Field(None, max_length=32)
    key: str | None = Field(None, max_length=64)
    card: CardId | None = None
    edition: Literal["foil", "holo", "polychrome", "negative", "none"] | None = None
    seal: Literal["Gold", "Red", "Blue", "Purple", "none"] | None = None
    enhancement: str | None = Field(None, max_length=32)
    rank: str | None = Field(None, max_length=8)
    suit: Literal["Spades", "Hearts", "Clubs", "Diamonds"] | None = None
    to: Literal["hand", "deck"] | None = None
    eternal: bool | None = None
    perishable: bool | None = None
    rental: bool | None = None
    expected_version: Version = None

    def to_dto(self) -> CreativeCommand:
        value = None if self.value is None else (int(self.value) if self.value == int(self.value) else self.value)
        return CreativeCommand(op=self.op, what=self.what, value=value, hand=self.hand, key=self.key,
                               card=self.card, edition=self.edition, seal=self.seal, enhancement=self.enhancement,
                               rank=self.rank, suit=self.suit, to=self.to, eternal=self.eternal,
                               perishable=self.perishable, rental=self.rental)


class PlayerSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    private: bool | None = Field(None, description="Only your name shows on your profile, and your runs can't be "
                                                   "watched")
    all_unlocked: bool | None = Field(None, description="New runs fully unlocked (accounts whose roles allow it)")

    def to_dto(self) -> PlayerSettings:
        return PlayerSettings(private=self.private, all_unlocked=self.all_unlocked)


# ------------------------------------------------------------------ multiplayer
Seed = Annotated[str | None, Field(None, pattern=r"^[A-Za-z0-9]{1,8}$",
                                   description="1 to 8 letters or digits; none for a random seed (the same for both)")]
Timer = Annotated[int, Field(120, json_schema_extra={"enum": [60, 120, 180, 300]},
                             description="Seconds a player has once the other one waits for them: 60, 120, 180 or 300")]
GameSpeed = Annotated[float, Field(1, json_schema_extra={"enum": [0.5, 1, 2, 4]},
                                   description="The player's game speed setting (their run's)")]


class NewMatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["pvp", "coop"] = Field("pvp", description="pvp: each player their own run, hit points; coop: one "
                                                         "run for both, in turns")
    deck: str = Field("b_red", description="The deck both players play")
    stake: int = Field(1, ge=1, le=8)
    seed: Seed = None
    timer: Timer = 120
    game_speed: GameSpeed = 1

    def to_dto(self) -> NewMatch:
        return NewMatch(mode=self.mode, deck=self.deck, stake=self.stake, seed=self.seed, timer=self.timer,
                        game_speed=float(self.game_speed))


class MatchSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deck: str = "b_red"
    stake: int = Field(1, ge=1, le=8)
    seed: Seed = None
    timer: Timer = 120

    def to_dto(self) -> MatchSettingsChange:
        return MatchSettingsChange(deck=self.deck, stake=self.stake, seed=self.seed, timer=self.timer)


class JoinMatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., min_length=4, max_length=12, description="The match's invite code")
    game_speed: GameSpeed = 1


class VoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    choice: Literal["select", "skip"] = Field(..., description="Play the blind on deck, or skip it (both must skip)")


class SelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cards: list[int] = Field(default_factory=list, max_length=8, description="Hand card ids")


class KickRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seat: int = Field(ge=0, le=1, description="The seat of the player to send away")


class EmoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    emote: EmoteName
