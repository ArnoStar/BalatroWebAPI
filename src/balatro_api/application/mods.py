"""Content mods: checking packages, the community registry (publish, browse,
download, install), and the mods a run is started with.

A package is checked by the engine (its format, then a short run played with
it) before the API keeps it.  Packages are kept by content hash for good: a
published version never changes, a run names its packages by hash, and
unlisting a mod only hides it from the registry (runs still replay).  Only a
mod's publisher (or an admin) publishes its next versions or unlists it.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import Any

from balatro_api.domain import (
    OFFICIAL,
    InvalidMod,
    ModForbidden,
    ModIdTaken,
    ModNotFound,
    ModRecord,
    ModRef,
    ModVersion,
    ModVersionExists,
    logic,
    package_hash,
    version_key,
)

from .dto import ModCheck, ModChoice, ModDetailView, ModListView, ModSummaryView, ModVersionView, Player
from .permissions import Permission, allowed
from .ports import Clock, GameEngine, ModRepository

log = logging.getLogger(__name__)

OFFICIAL_NAME = "Balatro"


def _size(package: dict[str, Any]) -> int:
    return len(json.dumps(package, ensure_ascii=False).encode())


def summary_view(r: ModRecord, player: Player | None = None) -> ModSummaryView:
    return ModSummaryView(id=r.id, name=r.name, version=r.latest_version, hash=r.latest_hash,
                          description=r.description, tags=list(r.tags),
                          author=OFFICIAL_NAME if r.official else r.owner_name, official=r.official,
                          installs=r.installs, summary=dict(r.summary), created_at=r.created_at,
                          updated_at=r.updated_at, loc=dict(r.loc),
                          yours=player is not None and r.owned_by(player.id) and not r.official)


def _manages(player: Player) -> bool:
    return allowed(player, Permission.MANAGE_MODS)


class ModPackages:
    """Turns the mods a client asks for into packages the engine plays (and keeps new ones)."""

    def __init__(self, engine: GameEngine, mods: ModRepository, clock: Clock) -> None:
        self.engine, self.mods, self.clock = engine, mods, clock

    def check(self, package: Any) -> ModCheck:
        if not isinstance(package, dict):
            return ModCheck(valid=False, errors=["a mod's package is a JSON object"])
        errors = self.engine.check_mod(package)
        ok = not errors
        return ModCheck(valid=ok, errors=errors, id=package.get("id") if isinstance(package.get("id"), str) else None,
                        version=package.get("version") if isinstance(package.get("version"), str) else None,
                        name=package.get("name") if isinstance(package.get("name"), str) else None,
                        hash=package_hash(package) if ok else None,
                        summary=self.engine.mod_summary(package) if ok else {}, size=_size(package))

    def keep(self, package: dict[str, Any]) -> ModRef:
        """Check a package the server doesn't have yet, and keep it."""
        h = package_hash(package)
        if self.mods.package(h) is None:
            check = self.check(package)
            if not check.valid:
                raise InvalidMod(check.errors, check.id)
            self.mods.put_package(h, package, self.clock.now())
        return ModRef.of(package)

    def published(self, mod_id: str, version: str | None, player: Player | None = None) -> dict[str, Any]:
        """A published mod's package (its latest version, or ``version``)."""
        record = self.mods.get_mod(mod_id)
        if record is None or (not record.listed and not (player is not None and (
                record.owned_by(player.id) or _manages(player)))):
            raise ModNotFound(mod_id)
        h = record.latest_hash
        if version is not None and version != record.latest_version:
            found = next((v for v in self.mods.versions(mod_id) if v.version == version), None)
            if found is None:
                raise ModNotFound(f"{mod_id} {version}")
            h = found.hash
        package = self.mods.package(h)
        if package is None:
            raise ModNotFound(f"{mod_id} {version or record.latest_version}")
        return package

    def resolve(self, player: Player, choices: Sequence[ModChoice]) -> tuple[tuple[ModRef, ...], dict[str, Any]]:
        """The run's mod references and their logic (by hash)."""
        refs: list[ModRef] = []
        packages: dict[str, dict[str, Any]] = {}
        for c in choices:
            if c.package is not None:
                package = c.package
                ref = self.keep(package)
            elif c.hash is not None:
                found = self.mods.package(c.hash)
                if found is None:
                    raise ModNotFound(c.hash)
                package = found
                ref = ModRef.of(package)
            elif c.id is not None:
                package = self.published(c.id, c.version, player)
                ref = ModRef.of(package)
            else:
                raise InvalidMod(["a mod is a package, a published mod's id, or a package's hash"])
            refs.append(ref)
            packages[ref.hash] = logic(package)
        return tuple(refs), packages


class ValidateMod:
    """Check a package without keeping it (for importing a file, and for a mod editor)."""

    def __init__(self, packages: ModPackages) -> None:
        self.packages = packages

    def __call__(self, player: Player, package: Any) -> ModCheck:
        return self.packages.check(package)


class PublishMod:
    """Publish a mod, or a new version of one's own mod, in the registry."""

    def __init__(self, packages: ModPackages, mods: ModRepository, clock: Clock) -> None:
        self.packages, self.mods, self.clock = packages, mods, clock

    def __call__(self, player: Player, package: Any, official: bool = False) -> ModDetailView:
        check = self.packages.check(package)
        if not check.valid or check.id is None or check.version is None or check.hash is None:
            raise InvalidMod(check.errors, check.id)
        owner = OFFICIAL if official else player.id
        record = self.mods.get_mod(check.id)
        if record is not None:
            if record.official and not official:
                raise ModIdTaken(f"{check.id!r} is an official mod's id")
            if not official and not record.owned_by(player.id) and not _manages(player):
                raise ModIdTaken(f"another player published a mod with the id {check.id!r}: choose another id")
            if version_key(check.version) <= version_key(record.latest_version):
                raise ModVersionExists(f"{check.id} {check.version} isn't newer than the published "
                                       f"{record.latest_version}")
        now = self.clock.now()
        self.mods.put_package(check.hash, package, now)
        self.mods.add_version(ModVersion(mod_id=check.id, version=check.version, hash=check.hash, created_at=now,
                                         size=check.size))
        loc = package.get("loc") if isinstance(package.get("loc"), dict) else {}
        updated = ModRecord(
            id=check.id, owner=record.owner if record is not None else owner,
            owner_name=OFFICIAL_NAME if official else (player.name or (record.owner_name if record else None)),
            name=check.name or check.id, description=str(package.get("description", "")),
            tags=[str(t) for t in package.get("tags", [])], latest_version=check.version, latest_hash=check.hash,
            summary=check.summary, created_at=record.created_at if record is not None else now, updated_at=now,
            official=official or (record.official if record is not None else False), listed=True,
            installs=record.installs if record is not None else 0, loc=loc)
        self.mods.save_mod(updated)
        return _detail(self.mods, updated, player)


def _detail(mods: ModRepository, record: ModRecord, player: Player | None) -> ModDetailView:
    s = summary_view(record, player)
    return ModDetailView(**{f: getattr(s, f) for f in s.__dataclass_fields__},
                         versions=[ModVersionView(version=v.version, hash=v.hash, created_at=v.created_at,
                                                  size=v.size) for v in mods.versions(record.id)])


class ListMods:
    """Browse the registry: search the id, name and description, filter by tag, sort."""

    def __init__(self, mods: ModRepository) -> None:
        self.mods = mods

    def __call__(self, player: Player, query: str | None = None, tag: str | None = None, sort: str = "popular",
                 limit: int = 30, offset: int = 0, mine: bool = False) -> ModListView:
        records, total = self.mods.find_mods(query, tag, sort, limit, offset, owner=player.id if mine else None)
        return ModListView(items=[summary_view(r, player) for r in records], total=total)


class GetMod:
    def __init__(self, mods: ModRepository) -> None:
        self.mods = mods

    def __call__(self, player: Player, mod_id: str) -> ModDetailView:
        record = self.mods.get_mod(mod_id)
        if record is None or (not record.listed and not record.owned_by(player.id) and not _manages(player)):
            raise ModNotFound(mod_id)
        return _detail(self.mods, record, player)


class DownloadMod:
    """A published mod's package (to install it, or export it to a file)."""

    def __init__(self, packages: ModPackages) -> None:
        self.packages = packages

    def __call__(self, player: Player, mod_id: str, version: str | None = None) -> dict[str, Any]:
        return self.packages.published(mod_id, version, player)


class GetModPackage:
    """A package by hash: the mods of a run being watched, or played on another device."""

    def __init__(self, mods: ModRepository) -> None:
        self.mods = mods

    def __call__(self, player: Player, package_id: str) -> dict[str, Any]:
        package = self.mods.package(package_id)
        if package is None:
            raise ModNotFound(package_id)
        return package


class UnlistMod:
    """Take a mod off the registry (its publisher, or an admin).  Its packages stay: runs replay with them."""

    def __init__(self, mods: ModRepository, clock: Clock) -> None:
        self.mods, self.clock = mods, clock

    def __call__(self, player: Player, mod_id: str) -> None:
        record = self.mods.get_mod(mod_id)
        if record is None or not record.listed:
            raise ModNotFound(mod_id)
        if record.official and not _manages(player):
            raise ModForbidden("an official mod stays")
        if not record.owned_by(player.id) and not _manages(player):
            raise ModNotFound(mod_id)  # (as for runs: someone else's is "not found" to change)
        record.listed = False
        record.updated_at = self.clock.now()
        self.mods.save_mod(record)


class InstallMod:
    """The player installed a mod (counted once per player)."""

    def __init__(self, mods: ModRepository, clock: Clock) -> None:
        self.mods, self.clock = mods, clock

    def __call__(self, player: Player, mod_id: str) -> ModSummaryView:
        record = self.mods.get_mod(mod_id)
        if record is None or not record.listed:
            raise ModNotFound(mod_id)
        record.installs = self.mods.add_install(mod_id, player.id, self.clock.now())
        return summary_view(record, player)


def publish_official_mods(engine: GameEngine, mods: ModRepository, publish: PublishMod) -> None:
    """Put the engine's example mods in the registry (each version once)."""
    nobody = Player(id=OFFICIAL, name=OFFICIAL_NAME)
    for package in engine.official_mods():
        record = mods.get_mod(str(package.get("id")))
        if record is not None and version_key(record.latest_version) >= version_key(str(package.get("version"))):
            continue
        try:
            publish(nobody, package, official=True)
        except Exception:
            log.exception("the official mod %r wasn't published", package.get("id"))


__all__ = ["DownloadMod", "GetMod", "GetModPackage", "InstallMod", "ListMods", "ModPackages", "PublishMod",
           "UnlistMod", "ValidateMod", "publish_official_mods", "summary_view"]
