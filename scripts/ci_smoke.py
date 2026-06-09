"""CI smoke test: cross-platform sanity for the godot-grounding MCP.

Requires data/extension_api.json (dumped by the CI step). Runs without a real game
project — uses throwaway fixtures. Exits non-zero on any failure.
"""
import asyncio
import os
import pathlib
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]

# Point the server at a throwaway fixture project before importing config.
_fix = pathlib.Path(tempfile.mkdtemp(prefix="gmcp_ci_"))
(_fix / "project.godot").write_text('config_version=5\n\n[application]\nconfig/name="CI Fixture"\n', encoding="utf-8")
os.environ["GODOT_PROJECT"] = str(_fix)
sys.path.insert(0, str(REPO / "src"))

from godot_mcp import engine_api, init as initmod, lint  # noqa: E402
from godot_mcp.server import mcp  # noqa: E402

fails: list[str] = []


def check(name: str, cond: bool) -> None:
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


# 1) tools register — exact roster assertion (F-9)
# This set is the authoritative tool roster from server.py.  If a tool is
# added, removed, or renamed, this assertion will fail until the set is
# intentionally updated here.
EXPECTED_TOOLS = {
    "godot_version",
    "godot_doctor",
    "godot_class",
    "godot_member",
    "godot_search",
    "project_convention",
    "project_catalog",
    "project_index",
    "project_find_files",
    "project_scene",
    "godot_lint_scene",
    "project_find_refs",
    "godot_lint",
    "godot_lint_source",
    "godot_write_script",
    "godot_fix_script",
    "godot_patch_script",
    "godot_run_tests",
    "godot_check",
    "godot_run_script",
    "godot_validate",
    "godot_editor_ping",
    "godot_run_game",
    "godot_stop_game",
    "godot_editor_scene_tree",
    "godot_open_scene",
    "project_input_actions",
    "project_setting",
    "project_classes",
    "project_layers",
}

names = {t.name for t in asyncio.run(mcp.list_tools())}
missing = EXPECTED_TOOLS - names
extra = names - EXPECTED_TOOLS
roster_ok = not missing and not extra
roster_msg = "exact tool roster matches"
if not roster_ok:
    parts = []
    if missing:
        parts.append(f"missing: {sorted(missing)}")
    if extra:
        parts.append(f"extra/renamed: {sorted(extra)}")
    roster_msg = "tool roster mismatch — " + "; ".join(parts)
check(roster_msg, roster_ok)

# 2) engine grounding (from dumped extension_api.json)
node = engine_api.get_class("Node")
check("godot_class(Node) has add_child", "add_child" in node)
check("godot_member move_and_slide", "move_and_slide" in engine_api.get_member("CharacterBody2D", "move_and_slide"))
check("godot_search body_entered finds signal", "[signal]" in engine_api.search("body_entered", 5))

# 3) linter: clean passes, bad is flagged
good = "extends Node\n\nfunc f(x: int) -> void:\n\tvar y: int = x\n\tprint(y)\n"
bad = "extends Node\n\nfunc Bad(a):\n\tvar z = a\n\treturn z\n"
check("lint clean -> 0 findings", len(lint.lint_source(good)) == 0)
check("lint bad -> has errors", any(f["severity"] == "error" for f in lint.lint_source(bad, "res://b.gd")))

# 4) init scaffolds a project
proj = pathlib.Path(tempfile.mkdtemp(prefix="gmcp_ci_proj_"))
(proj / "project.godot").write_text('config_version=5\n\n[application]\nconfig/name="Scaffold"\n', encoding="utf-8")
initmod.main([str(proj)])
for rel in ("godot-mcp.toml", ".mcp.json", ".claude/agents/godot-editor.md", ".claude/skills/godot/SKILL.md", ".codex/agents/godot-editor.toml"):
    check(f"init wrote {rel}", (proj / rel).exists())

print()
if fails:
    print("FAILED: " + ", ".join(fails))
    sys.exit(1)
print("ALL PASS")
