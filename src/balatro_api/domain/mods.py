"""Content mods as the API keeps them: packages, the community registry, and
the mods a run is played with.

A package is the engine's (BalatroEngine's format; the engine checks it).
Here it is opaque JSON with an id, a version and a content hash: a run names
the packages it was started with by hash (``ModRef``), and packages are kept
by hash for good, so a run always replays with exactly its mods.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .errors import DomainError

MAX_RUN_MODS = 16
OFFICIAL = "official"  # the owner of the mods that come with the engine
VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
MOD_SORTS = ("popular", "new", "updated", "name")


def package_hash(package: Mapping[str, Any]) -> str:
    """The package's content hash (sha256 of its canonical JSON): two equal packages have the same."""
    canonical = json.dumps(package, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def logic(package: Mapping[str, Any]) -> dict[str, Any]:
    """The package without its images (all the engine needs)."""
    return {k: v for k, v in package.items() if k != "assets"}


def version_key(version: str) -> tuple[int, int, int]:
    m = VERSION.match(version)
    if m is None:
        return (0, 0, 0)
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


@dataclass(frozen=True)
class ModRef:
    """A mod a run is played with: the package's id, version and content hash."""

    id: str
    version: str
    hash: str
    name: str = ""
    creative: bool = False

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "version": self.version, "hash": self.hash, "name": self.name,
                "creative": self.creative}

    @staticmethod
    def from_json(d: Mapping[str, Any]) -> ModRef:
        return ModRef(id=d["id"], version=d["version"], hash=d["hash"], name=d.get("name", ""),
                      creative=bool(d.get("creative")))

    @staticmethod
    def of(package: Mapping[str, Any]) -> ModRef:
        return ModRef(id=str(package.get("id")), version=str(package.get("version")), hash=package_hash(package),
                      name=str(package.get("name", "")), creative=bool(package.get("creative")))


@dataclass
class ModRecord:
    """A mod published in the registry (its versions are packages, kept by hash)."""

    id: str
    owner: str
    owner_name: str | None
    name: str
    description: str
    tags: list[str]
    latest_version: str
    latest_hash: str
    summary: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    official: bool = False
    listed: bool = True
    installs: int = 0
    loc: dict[str, Any] = field(default_factory=dict)

    def owned_by(self, player_id: str) -> bool:
        return self.owner == player_id


@dataclass(frozen=True)
class ModVersion:
    mod_id: str
    version: str
    hash: str
    created_at: datetime
    size: int = 0


class ModNotFound(DomainError):
    code = "mod_not_found"

    def __init__(self, what: str) -> None:
        super().__init__(f"no mod {what!r}")


class InvalidMod(DomainError):
    """A package the engine can't play: ``errors`` says why, each with its place in the package."""

    code = "invalid_mod"

    def __init__(self, errors: list[str], mod_id: str | None = None) -> None:
        head = f"the mod {mod_id!r} isn't valid" if mod_id else "the mod isn't valid"
        super().__init__(f"{head}: {errors[0]}" if errors else head)
        self.errors = list(errors)


class ModIdTaken(DomainError):
    """Another player published a mod with this id: only its owner publishes its versions."""

    code = "mod_id_taken"


class ModVersionExists(DomainError):
    """This version of the mod is published already (a new one needs a higher version)."""

    code = "mod_version_exists"


class ModForbidden(DomainError):
    code = "mod_forbidden"
