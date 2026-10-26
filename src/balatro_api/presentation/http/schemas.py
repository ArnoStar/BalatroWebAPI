"""Request bodies.  (Responses are the application's dataclasses.)"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from balatro_api.application.dto import ImportedRun, NewGame, PlayerAction, PlayerSettings

Version = Annotated[int | None, Field(
    default=None, ge=0,
    description="The game version the action is meant for (GameView.version). If the game has moved on, the "
                "action is refused with 409 version_conflict instead of being applied to another state.")]
CardId = Annotated[int, Field(description="A card id (CardView.id)")]


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

    def to_dto(self) -> NewGame:
        return NewGame(seed=self.seed, deck=self.deck, stake=self.stake, challenge=self.challenge,
                       game_speed=float(self.game_speed))


class _Action(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: Version = None

    def to_dto(self) -> PlayerAction:
        fields = self.model_dump(exclude={"expected_version"})
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


class ImportGameRequest(BaseModel):
    """A run's history (``GET /games/{id}/history``: its settings and
    commands), to rebuild it as a new run of the caller's."""

    model_config = ConfigDict(extra="ignore")

    settings: ImportSettings
    commands: list[dict[str, Any]] = Field(default_factory=list, max_length=20000,
                                           description="engine commands, as in a history (indices into the areas)")
    start_profile: dict[str, Any] | None = Field(None, description="the history's start_profile")

    def to_dto(self) -> ImportedRun:
        s = self.settings
        # (a history from before progress was kept has no start profile: it rebuilds as a seeded run did)
        return ImportedRun(seed=s.seed, deck=s.deck, stake=s.stake, challenge=s.challenge,
                           game_speed=float(s.game_speed), commands=tuple(self.commands),
                           seeded=s.seeded if self.start_profile is not None else True,
                           start_profile=self.start_profile)


class PlayerSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    private: bool | None = Field(None, description="Only your name shows on your profile, and your runs can't be "
                                                   "watched")
    all_unlocked: bool | None = Field(None, description="New runs fully unlocked (accounts whose roles allow it)")

    def to_dto(self) -> PlayerSettings:
        return PlayerSettings(private=self.private, all_unlocked=self.all_unlocked)
