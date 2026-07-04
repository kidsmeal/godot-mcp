"""godot-grounding MCP server.

Two grounding halves + a validation/edit loop, all driven by a per-project profile
(godot-mcp.toml) so the same server works on any Godot project:
  * Engine  — exact, version-pinned Godot API (godot_*)
  * Project — the target project's conventions, catalogs, map (project_*)
  * Loop    — lint, parse-checked edit, headless tests (godot_lint/write/run_*)
"""
from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from godot_mcp import (
    bridge,
    catalogs,
    config,
    doctor,
    edit,
    engine_api,
    lint,
    procgen,
    project_ground,
    refs,
    runner,
    scene,
)

mcp = FastMCP(
    "godot-grounding",
    instructions="""\
Shared conventions for every tool below (not repeated per-tool):

- Paths: any script_path/scene_path argument is a project-relative res:// path.
- Containment: a path that escapes the project root is refused, always in the
  same shape: "Refused: <path> resolves outside the project root."
- Suppressing a lint finding: add `# lint: ignore` on the offending line to
  suppress all findings on it, or `# lint: ignore=rule,rule` to suppress only
  the named rule(s) (comma-separated).
- The grounding loop this server is built around: ground first (godot_class,
  godot_member, project_convention, project_catalog, etc.) before writing code,
  then make linted edits (godot_write_script/godot_patch_script/godot_fix_script,
  which parse-check and roll back on error), then confirm with a test/run step
  (godot_check, godot_validate, godot_run_tests) before trusting the result.
""",
)


# --- Engine grounding -------------------------------------------------------
@mcp.tool()
def godot_version() -> str:
    """Report the Godot version the engine API is grounded to (from the dumped
    extension_api.json) and the target project's name + configured features."""
    ver = "unknown (extension_api.json not dumped yet — run scripts/dump_api.ps1)"
    if config.EXTENSION_API.exists():
        try:
            h = json.loads(config.EXTENSION_API.read_text(encoding="utf-8")).get("header", {})
            ver = h.get("version_full_name") or f'{h.get("version_major")}.{h.get("version_minor")}'
        except Exception:
            pass
    return f"Engine API grounded to: {ver}\nProject: {config.PROFILE.name} ({config.PROJECT_ROOT})\nFeatures: {config.project_version()}"


@mcp.tool()
def godot_doctor() -> str:
    """Health check: verifies the engine API dump (and that its version matches the
    project), the Godot binary is resolvable, gdtoolkit is installed, and the profile's
    catalog/doc/test-scene paths exist. Run this first when something seems off."""
    return doctor.report()


@mcp.tool()
def godot_class(name: str, include_inherited: bool = False, full_docs: bool = False) -> str:
    """Exact API for a Godot engine class at the project's pinned version:
    inheritance, methods (full signatures), properties, signals, enums, constants.
    Consult this BEFORE calling any engine API to avoid hallucinated/renamed members.
    Set include_inherited=True to also list members inherited from ancestor classes,
    each labeled with their origin class (e.g. add_child from Node).
    Doc descriptions are compact by default (first sentence only); set
    full_docs=True for the fuller (still char-capped) description text."""
    return engine_api.get_class(name, include_inherited, full_docs)


@mcp.tool()
def godot_member(class_name: str, member: str, full_docs: bool = False) -> str:
    """Exact signature of a single method, property, signal, enum, or constant on a
    Godot class. Use to confirm argument order/types before writing a call.
    Doc descriptions are compact by default (first sentence only); set
    full_docs=True for the fuller (still char-capped) description text."""
    return engine_api.get_member(class_name, member, full_docs)


@mcp.tool()
def godot_search(query: str, limit: int = 25) -> str:
    """Search the grounded Godot API for classes, methods, signals, and properties
    matching a keyword (e.g. 'collision', 'tween', 'body_entered')."""
    return engine_api.search(query, limit)


# --- Project grounding (profile-driven) -------------------------------------
@mcp.tool()
def project_convention(topic: str = "") -> str:
    """Search this project's convention/design docs (configured in godot-mcp.toml
    [docs]) for a topic — e.g. 'signal naming', 'enemy creation'. Call with no topic
    to list the available docs and their headings."""
    return project_ground.convention(topic)


@mcp.tool()
def project_catalog(kind: str = "all") -> str:
    """List a project catalog parsed from source per the profile's [[catalog]] specs
    (e.g. effect_types, damage_types, sticker_bases), plus built-in 'autoloads', or
    'all'. Use to ground content work in values that actually exist."""
    return catalogs.catalog(kind)


@mcp.tool()
def project_index() -> str:
    """Return the project's configured index / codebase-map doc (profile [docs] entry
    named by index_doc): entry points, autoloads, systems, and where things live."""
    return project_ground.index()


@mcp.tool()
def project_find_files(subdir: str = ".", pattern: str = "*", limit: int = 500) -> str:
    """Reliable recursive file listing under the project (res:// paths), avoiding the
    Windows glob-miss gotcha. subdir is relative to project root; pattern is a
    filename glob like '*.gd' or 'hero_*.tscn'."""
    return project_ground.find_files(subdir, pattern, limit)


@mcp.tool()
def project_scene(scene_path: str) -> str:
    """Summarize a .tscn without opening the editor: header (uid/format), ext_resource
    dependencies, sub_resources, the node tree (name, type or instanced scene, attached
    script), and signal connections."""
    return scene.describe(scene_path)


@mcp.tool()
def godot_lint_scene(scene_path: str) -> str:
    """Lint a .tscn for silent breakage: ext_resource paths that don't exist,
    .godot/imported references, and type-as-name nodes (e.g. a node literally named
    'Area2D')."""
    try:
        config.resolve_project_path(scene_path)
    except config.PathEscapeError:
        return f"Refused: {scene_path} resolves outside the project root."
    return lint.format_findings(scene.lint_scene(scene_path))


@mcp.tool()
def project_find_refs(symbol: str, kind: str = "all", limit: int = 200) -> str:
    """Find references to an identifier (function, class_name, signal, const, type)
    across all project .gd files, classified by kind: def, call, type, member, extends,
    ref. Comment/string-aware (beats grep) and Windows-glob-safe — use before a rename
    or to gauge a change's blast radius. kind filters the listing ('all','def','call',
    'type','member','extends','ref'). Name-based, not type-resolved."""
    return refs.find_refs(symbol, kind, limit)


@mcp.tool()
def project_input_actions() -> str:
    """List all input actions for this project: project-defined actions (from [input]
    in project.godot) and the standard built-in ui_* actions. Use to ground any
    code that calls Input.is_action_pressed/just_pressed/etc. with an action string."""
    return project_ground.input_actions()


@mcp.tool()
def project_setting(name: str, resolve: bool = False) -> str:
    """Read a project setting from project.godot by dotted key (e.g.
    'application/config/name', 'display/window/size/viewport_width').
    resolve=True optionally resolves via a headless Godot probe so default-overrides
    are applied; degrades gracefully if Godot is unavailable."""
    return project_ground.setting(name, resolve)


@mcp.tool()
def project_classes() -> str:
    """Scan all project .gd files for class_name declarations and return a map of
    ClassName -> res://path. Cached against the .gd file signature so repeated calls
    are fast. Use to verify a class_name exists before extending or typing it."""
    return project_ground.classes()


@mcp.tool()
def project_layers() -> str:
    """List named physics, render, navigation, and avoidance layers from the
    [layer_names] section of project.godot. Grouped by category (2d_physics,
    3d_render, 2d_navigation, avoidance, …) showing layer number → name."""
    return project_ground.layers()


# --- Convention-linted edits ------------------------------------------------
@mcp.tool()
def godot_lint(script_path: str) -> str:
    """Lint an existing GDScript against this project's conventions: strict typing
    (var/param/return), past-tense signals (no on_ prefix), PascalCase class_name,
    ALL_CAPS consts, snake_case funcs, no .godot/imported refs, plus profile catalog
    typo checks. Pure read — does not modify the file."""
    try:
        target = config.resolve_project_path(script_path)
    except config.PathEscapeError:
        return f"Refused: {script_path} resolves outside the project root."
    src = config.read_text(target)
    if src is None:
        return f"Not found: {script_path}"
    return lint.format_findings(lint.lint_source(src, script_path, catalog_refs=catalogs.build_catalog_refs(), input_actions=project_ground.input_action_set()))


@mcp.tool()
def godot_lint_source(source: str, path: str = "") -> str:
    """Lint a GDScript snippet/string BEFORE writing it (same rules as godot_lint).
    'path' is optional context for test-only rules."""
    return lint.format_findings(lint.lint_source(source, path, catalog_refs=catalogs.build_catalog_refs(), input_actions=project_ground.input_action_set()))


@mcp.tool()
def godot_write_script(script_path: str, content: str, enforce_conventions: bool = False) -> str:
    """Write a full GDScript file safely: backs up, writes, runs Godot --check-only,
    and ROLLS BACK on any parse error (never leaves the project non-parsing). Returns
    lint findings. enforce_conventions=True refuses writes that have convention errors."""
    return edit.write_script(script_path, content, enforce_conventions)


@mcp.tool()
def godot_fix_script(script_path: str) -> str:
    """Apply safe, mechanical lint fixes and re-verify through the parse-checked writer
    (rolls back if anything breaks): untyped `var x = v` → `var x := v`, and add `-> void`
    to functions with no value-returning return."""
    return edit.auto_fix(script_path)


@mcp.tool()
def godot_patch_script(script_path: str, old_string: str, new_string: str, enforce_conventions: bool = False) -> str:
    """Replace an exact unique substring in a GDScript, then parse-check with rollback
    (like godot_write_script). old_string must match the file exactly and uniquely."""
    return edit.patch_script(script_path, old_string, new_string, enforce_conventions)


# --- Validation / feedback loop ---------------------------------------------
@mcp.tool()
def godot_run_tests(filter: str = "", integration: bool = False, timeout: int = 300) -> str:
    """Run the project's headless test suite (profile [tests]) and return a structured
    pass/fail summary: files run, tests/assertions passed-failed, failing files, failed
    assertions. 'filter' is passed to the runner as `-- --test-filter <filter>`.
    integration=True runs the integration scene. Exit code 0 = all passed.

    Note (C28): --test-filter is only understood by the 'custom' test framework runner.
    With gut or gdunit4, the filter argument is passed but may be silently ignored by
    the framework — the full suite runs and the result still reports as complete."""
    return runner.run_tests(filter, integration, timeout)


@mcp.tool()
def godot_check(script_path: str, timeout: int = 60) -> str:
    """Parse-check a single GDScript WITHOUT running it (`--check-only --script`).
    Catches syntax/parse/type errors before F5."""
    return runner.check_script(script_path, timeout)


@mcp.tool()
def godot_run_script(script_path: str, timeout: int = 120) -> str:
    """Run a headless GDScript that `extends SceneTree`/`MainLoop` (e.g. dev/validator
    scripts) and return its output + exit code. Refuses other scripts (which can pop a
    blocking editor dialog)."""
    return runner.run_script(script_path, timeout)


@mcp.tool()
def godot_validate(script_path: str, timeout: int = 60) -> str:
    """Validate a GDScript with the project's autoloads fully registered.

    Unlike godot_check (--check-only, no SceneTree), this boots the project
    SceneTree so all autoloads are available as global identifiers.  Catches
    'not declared' errors on autoload references that --check-only misses.

    Uses the plugin-owned data/validate_script.gd harness — the harness runs by
    absolute path and is NEVER written into the project, so there is no leak risk.
    Verdict comes from the engine log (exit code is unreliable for this harness)."""
    return runner.validate_with_autoloads(script_path, timeout)


# --- Live editor bridge (optional 'Godot Grounding Bridge' addon) -----------
@mcp.tool()
def editor_ping() -> str:
    """Check the live editor bridge: returns the running Godot editor version if the
    'Godot Grounding Bridge' addon is enabled and the editor is open, else how to fix it.
    Call this before the other editor_* bridge tools."""
    return bridge.ping()


@mcp.tool()
def editor_run_game(scene: str = "main") -> str:
    """Play the project in the open Godot editor: scene='main' (the project main scene)
    or 'current' (the scene being edited). Requires the editor bridge addon."""
    return bridge.run_game(scene)


@mcp.tool()
def editor_stop_game() -> str:
    """Stop the running game in the Godot editor (editor bridge addon required)."""
    return bridge.stop_game()


@mcp.tool()
def editor_scene_tree() -> str:
    """Return the node tree of the scene currently open in the Godot editor (live, via the
    editor bridge addon)."""
    return bridge.scene_tree()


@mcp.tool()
def editor_open_scene(scene_path: str) -> str:
    """Open a scene in the Godot editor via the editor bridge addon."""
    try:
        resolved = config.resolve_project_path(scene_path)
    except config.PathEscapeError:
        return f"Refused: {scene_path} resolves outside the project root."
    if not resolved.exists():
        return f"Not found: {scene_path}"
    return bridge.open_scene(scene_path)


# --- Procgen tool suite (procgen_*) -----------------------------------------
@mcp.tool()
def procgen_tileset_build(config_path: str, out_path: str) -> str:
    """Build a `.tres` TileSet from a declarative TOML config, headless.

    config_path is a filesystem path to the TOML config (atlas sources, terrain
    sets + peering-bit strategy, tile-animation groups, physics/custom-data
    layers). out_path is the project-relative res:// path to write the TileSet
    to. Python validates the config (water-bottom law: at most one terrain per
    terrain set; water-bearing animated tiles must be mode='default'), composes
    and parse-checks one GDScript, runs it headless, and reports tiles created,
    animated groups, reserved frame regions, peering bits assigned, and a reload
    sanity check. The built-in terrain solver is never used (issues #76493 /
    #89844); peering bits are assigned directly for the in-house matcher."""
    return procgen.tileset_build(config_path, out_path)


@mcp.tool()
def procgen_terrain_audit(tileset_path: str, terrain_set: int = -1) -> str:
    """Audit a `.tres` TileSet's terrain-peering-bit coverage against the
    water-bottom law, headless.

    tileset_path is the project-relative res:// path to the TileSet.
    terrain_set=-1 (default) audits every terrain set; pass a specific index
    to scope the coverage table to just that set. Reports, per terrain set,
    the expected signature-class set for the set's mode (derived from the
    mode's valid peering bits, e.g. 47 classes for MATCH_CORNERS_AND_SIDES,
    16 for MATCH_SIDES/MATCH_CORNERS — never a hardcoded count) and which
    signatures are covered / missing / duplicated (duplicates are allowed —
    flagged as variants, since the in-house matcher's seeded pick consumes
    them). Also flags: tiles with terrain != -1 but terrain_set == -1
    (broken ordering), terrain sets with more than one terrain (water-bottom
    law violation), unused tiles, and animation desync (every animated
    terrain tile must share identical frames/duration and mode=DEFAULT — an
    error, since it breaks coastline phase-sync). Returns a markdown report
    plus a machine `coverage` dict the game repo's in-house matcher consumes
    (shape documented in procgen.terrain_audit's docstring)."""
    return procgen.terrain_audit(tileset_path, terrain_set)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
