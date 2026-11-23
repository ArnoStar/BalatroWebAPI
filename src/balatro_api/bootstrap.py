"""The composition root: the only place that knows every layer.  It picks
the adapters and builds the use cases with them."""

from __future__ import annotations

import logging
from typing import cast

from .application.locks import RunLocks
from .application.matches import (
    ChangeMatchSettings,
    CreateMatch,
    CurrentMatch,
    GetMatch,
    GetMatchHistory,
    GetMultiplayerGlobalStats,
    GetMultiplayerLeaderboard,
    GetMultiplayerStats,
    GetSteps,
    JoinMatch,
    KickPlayer,
    LeaveMatch,
    Matches,
    Rematch,
    SendEmote,
    SetSelection,
    StartMatch,
    VoteBlind,
)
from .application.mods import (
    DownloadMod,
    GetMod,
    GetModPackage,
    InstallMod,
    ListMods,
    ModPackages,
    PublishMod,
    UnlistMod,
    ValidateMod,
    publish_official_mods,
)
from .application.ports import (
    Authenticator,
    Clock,
    GameEngine,
    GameRepository,
    IdGenerator,
    MatchRepository,
    ModRepository,
)
from .application.use_cases import (
    Authenticate,
    CreateGame,
    CreativeChange,
    DeleteGame,
    GetCatalog,
    GetCoopDecks,
    GetGame,
    GetGameSummary,
    GetGlobalStats,
    GetHistory,
    GetLeaderboard,
    GetLegalActions,
    GetMe,
    GetPlayerProfile,
    GetPlayerStats,
    ImportGame,
    ListGames,
    PlayAction,
    PreviewHand,
    RunDebugCommand,
    UpdateMe,
    UseCases,
    WatchGame,
)
from .config import Settings
from .infrastructure.auth import AnonymousAuthenticator, JwtAuthenticator
from .infrastructure.engine import BalatroEngine
from .infrastructure.persistence import InMemoryGameRepository, PostgresGameRepository
from .infrastructure.system import SystemClock, UuidGenerator

log = logging.getLogger(__name__)


def build_authenticator(settings: Settings) -> Authenticator:
    if settings.auth_jwks_url and settings.auth_issuer:
        return JwtAuthenticator.from_jwks_url(settings.auth_jwks_url, settings.auth_issuer, settings.auth_audience)
    log.warning("sign-in is off (BALATRO_API_AUTH_JWKS_URL is not set): every caller is the same player")
    return AnonymousAuthenticator()


def build_repository(settings: Settings) -> GameRepository:
    if settings.database == "memory":
        log.warning("runs are kept in memory (BALATRO_API_DATABASE_URL=memory): they are lost when the server stops")
        return InMemoryGameRepository()
    return PostgresGameRepository(settings.database)


def build_use_cases(settings: Settings, engine: GameEngine | None = None, games: GameRepository | None = None,
                    ids: IdGenerator | None = None, clock: Clock | None = None,
                    authenticator: Authenticator | None = None,
                    match_repository: MatchRepository | None = None,
                    mod_repository: ModRepository | None = None, official_mods: bool = True) -> UseCases:
    """``official_mods``: put the engine's example mods in the registry (once per version)."""
    engine = engine or BalatroEngine(cache_size=settings.cache_size)
    if games is None:
        games = build_repository(settings)
    ids = ids or UuidGenerator()
    clock = clock or SystemClock()
    locks = RunLocks()
    me = GetMe(engine, games, settings.debug_commands)
    # (the repositories here keep matches too)
    matches = Matches(engine, games, match_repository or cast(MatchRepository, games), locks, clock, ids)
    mods = mod_repository or cast(ModRepository, games)  # (the repositories here keep mods too)
    packages = ModPackages(engine, mods, clock)
    publish = PublishMod(packages, mods, clock)
    if official_mods:
        publish_official_mods(engine, mods, publish)
    return UseCases(
        authenticate=Authenticate(authenticator or build_authenticator(settings)),
        create_game=CreateGame(engine, games, ids, clock, settings.debug_commands, packages),
        import_game=ImportGame(engine, games, ids, clock, settings.debug_commands, settings.admins, mods),
        get_game=GetGame(engine, games, matches),
        game_summary=GetGameSummary(games),
        list_games=ListGames(games),
        delete_game=DeleteGame(engine, games, locks),
        legal_actions=GetLegalActions(engine, games, matches),
        play_action=PlayAction(engine, games, locks, clock, matches),
        preview_hand=PreviewHand(engine, games, matches),
        history=GetHistory(games, matches),
        debug_command=RunDebugCommand(engine, games, locks, clock, enabled=settings.debug_commands,
                                      matches=matches),
        catalog=GetCatalog(engine),
        player_stats=GetPlayerStats(games, clock),
        leaderboard=GetLeaderboard(games),
        global_stats=GetGlobalStats(games),
        watch_game=WatchGame(engine, games, ids, clock, matches),
        me=me,
        update_me=UpdateMe(games, me),
        player_profile=GetPlayerProfile(engine, games, clock, matches),
        create_match=CreateMatch(matches),
        join_match=JoinMatch(matches),
        get_match=GetMatch(matches),
        current_match=CurrentMatch(matches),
        change_match=ChangeMatchSettings(matches),
        start_match=StartMatch(matches),
        vote_blind=VoteBlind(matches),
        leave_match=LeaveMatch(matches),
        set_selection=SetSelection(matches),
        coop_steps=GetSteps(matches),
        coop_decks=GetCoopDecks(engine, games, matches),
        rematch=Rematch(matches),
        kick_player=KickPlayer(matches),
        send_emote=SendEmote(matches),
        match_history=GetMatchHistory(matches),
        multiplayer_stats=GetMultiplayerStats(matches),
        multiplayer_leaderboard=GetMultiplayerLeaderboard(matches),
        multiplayer_global_stats=GetMultiplayerGlobalStats(matches),
        creative=CreativeChange(engine, games, locks, clock),
        validate_mod=ValidateMod(packages),
        publish_mod=publish,
        list_mods=ListMods(mods),
        get_mod=GetMod(mods),
        download_mod=DownloadMod(packages),
        mod_package=GetModPackage(mods),
        unlist_mod=UnlistMod(mods, clock),
        install_mod=InstallMod(mods, clock),
    )
