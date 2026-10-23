"""The dependency rule: each layer only imports the layers inside it.

    domain  <-  application  <-  infrastructure, presentation  <-  bootstrap, main

The engine (balatro) is only imported by infrastructure.engine, the web
framework only by presentation (and main, which serves it).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src" / "balatro_api"
WEB = ("fastapi", "starlette", "pydantic", "uvicorn")

ALLOWED = {
    "domain": {"domain"},
    "application": {"domain", "application"},
    "infrastructure": {"domain", "application", "infrastructure"},
    "presentation": {"domain", "application", "presentation"},
}


def imports(path: Path) -> set[str]:
    """Absolute module names a file imports (relative imports resolved)."""
    package = ".".join(path.relative_to(SRC.parent).with_suffix("").parts[:-1])
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")[: len(package.split(".")) - node.level + 1]
                out.add(".".join(base + ([node.module] if node.module else [])))
            elif node.module:
                out.add(node.module)
    return out


FILES = sorted(p for p in SRC.rglob("*.py"))


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(SRC)))
def test_layers(path: Path) -> None:
    layer = path.relative_to(SRC).parts[0]
    mods = imports(path)
    if layer in ALLOWED:
        used = {m.split(".")[1] for m in mods if m.startswith("balatro_api.") and len(m.split(".")) > 1}
        assert used <= ALLOWED[layer], f"{layer} imports {sorted(used - ALLOWED[layer])}"
        assert "balatro_api" not in mods or layer == "presentation", "import a layer, not the package root"
    engine = {m for m in mods if m == "balatro" or m.startswith("balatro.")}
    if engine:
        where = path.relative_to(SRC).parts[:2]
        assert where == ("infrastructure", "engine"), "only infrastructure.engine uses the engine"
    web = {m for m in mods if m.split(".")[0] in WEB}
    if web:
        assert layer == "presentation" or path.name == "main.py", f"{layer} uses the web framework: {sorted(web)}"
