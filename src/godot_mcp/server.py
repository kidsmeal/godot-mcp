"""godot-grounding MCP server (Phase 1).

Two grounding halves:
  * Engine  — exact, version-pinned Godot 4.6 API (godot_*)
  * Project — Capsule Castle's own conventions, catalogs, map (capsule_*)
"""
from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from godot_mcp import catalogs, config, engine_api, project_ground

mcp = FastMCP("godot-grounding")


# --- Engine grounding -------------------------------------------------------
@mcp.tool()
def godot_version() -> str:
    """Report the Godot version the engine API is grounded to (from the dumped
    extension_api.json) and the target project's configured Godot features."""
    ver = "unknown (extension_api.json not dumped yet — run scripts/dump_api.ps1)"
    if config.EXTENSION_API.exists():
        try:
            h = json.loads(config.EXTENSION_API.read_text(encoding="utf-8")).get("header", {})
            ver = h.get("version_full_name") or f'{h.get("version_major")}.{h.get("version_minor")}'
        except Exception:
            pass
    return f"Engine API grounded to: {ver}\nProject ({config.PROJECT_ROOT.name}) features: {config.project_version()}"


@mcp.tool()
def godot_class(name: str) -> str:
    """Exact API for a Godot engine class at the project's pinned version:
    inheritance, methods (full signatures), properties, signals, enums, constants.
    Consult this BEFORE calling any engine API to avoid hallucinated/renamed members."""
    return engine_api.get_class(name)


@mcp.tool()
def godot_member(class_name: str, member: str) -> str:
    """Exact signature of a single method, property, signal, enum, or constant on a
    Godot class. Use to confirm argument order/types before writing a call."""
    return engine_api.get_member(class_name, member)


@mcp.tool()
def godot_search(query: str, limit: int = 25) -> str:
    """Search the grounded Godot API for classes and methods matching a keyword
    (e.g. 'collision', 'tween', 'body_entered'). Returns 'Class' and 'Class.method' hits."""
    return engine_api.search(query, limit)


# --- Project grounding ------------------------------------------------------
@mcp.tool()
def capsule_convention(topic: str = "") -> str:
    """Search this project's conventions/design docs (AGENTS.md, CLAUDE.md, hero
    design guide, INDEX, new-hero checklist) for a topic — e.g. 'signal naming',
    'enemy creation', 'upgrade pool'. Call with no topic to list docs + headings."""
    return project_ground.convention(topic)


@mcp.tool()
def capsule_catalog(kind: str = "all") -> str:
    """List project game catalogs parsed from source: 'effect_types'
    (UpgradeEffectRegistry), 'sticker_bases', 'damage_types', 'autoloads', or 'all'.
    Use to ground content work in values that actually exist."""
    return catalogs.catalog(kind)


@mcp.tool()
def capsule_index() -> str:
    """Return the project's codebase map (docs/INDEX.md): entry points, autoloads,
    hero/enemy/UI systems, tests, and where things live."""
    return project_ground.index()


@mcp.tool()
def capsule_find_files(subdir: str = ".", pattern: str = "*", limit: int = 500) -> str:
    """Reliable recursive file listing under the project (res:// paths), avoiding the
    Windows glob-miss gotcha. subdir is relative to project root; pattern is a
    filename glob like '*.gd' or 'hero_*.tscn'."""
    return project_ground.find_files(subdir, pattern, limit)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
