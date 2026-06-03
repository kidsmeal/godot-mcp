"""godot-grounding MCP server (Phase 1).

Two grounding halves:
  * Engine  — exact, version-pinned Godot 4.6 API (godot_*)
  * Project — Capsule Castle's own conventions, catalogs, map (capsule_*)
"""
from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from godot_mcp import catalogs, config, edit, engine_api, lint, project_ground, runner

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


# --- Validation / feedback loop (Phase 2) -----------------------------------
@mcp.tool()
def godot_run_tests(filter: str = "", integration: bool = False, timeout: int = 300) -> str:
    """Run the project's headless test suite (res://tests/run_all.tscn) and return a
    structured pass/fail summary: files run, tests/assertions passed-failed, failing
    files, and failed-assertion messages. 'filter' matches test file path/name
    (e.g. 'armory', 'wave_clock'). integration=True runs res://tests/run_integration.tscn.
    Exit code 0 means all passed. Use after editing GDScript to confirm nothing broke."""
    return runner.run_tests(filter, integration, timeout)


@mcp.tool()
def godot_check(script_path: str, timeout: int = 60) -> str:
    """Parse-check a single GDScript WITHOUT running it (`--check-only --script`).
    Catches syntax/parse/type errors before F5. script_path is a res:// path."""
    return runner.check_script(script_path, timeout)


@mcp.tool()
def godot_run_script(script_path: str, timeout: int = 120) -> str:
    """Run a GDScript headlessly (`godot --headless --script <path>`) and return its
    output + exit code. For dev/generator/validator scripts (e.g. under
    tools/dev_scripts/) designed to run standalone. script_path is a res:// path."""
    return runner.run_script(script_path, timeout)


@mcp.tool()
def godot_verify_enemies(timeout: int = 120) -> str:
    """Run the project's existing headless enemy validator
    (tools/dev_scripts/verify_generated_enemies.gd) and return its report."""
    return runner.verify_enemies(timeout)


# --- Convention-linted edits (Phase 3) --------------------------------------
@mcp.tool()
def godot_lint(script_path: str) -> str:
    """Lint an existing GDScript against this project's AGENTS.md conventions:
    strict typing (var/param/return), past-tense signals (no on_ prefix), PascalCase
    class_name, ALL_CAPS consts, snake_case funcs, no .godot/imported refs. Reports
    line-numbered errors/warnings. Pure read — does not modify the file."""
    src = config.read_text(edit._abs(script_path))
    if src is None:
        return f"Not found: {script_path}"
    return lint.format_findings(lint.lint_source(src, script_path))


@mcp.tool()
def godot_lint_source(source: str, path: str = "") -> str:
    """Lint a GDScript snippet/string BEFORE writing it (same rules as godot_lint).
    Use to check generated code prior to saving. 'path' is optional context for
    test-only rules."""
    return lint.format_findings(lint.lint_source(source, path))


@mcp.tool()
def godot_write_script(script_path: str, content: str, enforce_conventions: bool = False) -> str:
    """Write a full GDScript file safely: backs up, writes, runs Godot --check-only,
    and ROLLS BACK on any parse error (never leaves the project non-parsing). Returns
    lint findings. enforce_conventions=True refuses writes that have convention errors.
    script_path is a res:// path."""
    return edit.write_script(script_path, content, enforce_conventions)


@mcp.tool()
def godot_patch_script(script_path: str, old_string: str, new_string: str, enforce_conventions: bool = False) -> str:
    """Replace an exact unique substring in a GDScript, then parse-check with rollback
    (like godot_write_script). old_string must match the file exactly and uniquely.
    script_path is a res:// path."""
    return edit.patch_script(script_path, old_string, new_string, enforce_conventions)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
