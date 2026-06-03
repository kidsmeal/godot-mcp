"""Quick smoke test of the grounding logic (run with the venv python)."""
import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from godot_mcp import catalogs, config, engine_api, project_ground  # noqa: E402
from godot_mcp.server import mcp  # noqa: E402


def show(title, body):
    print(f"\n===== {title} =====")
    print(body)


print("PROJECT_ROOT:", config.PROJECT_ROOT, "exists:", config.PROJECT_ROOT.exists())
print("EXTENSION_API exists:", config.EXTENSION_API.exists())

show("godot_search('body_entered')", engine_api.search("body_entered", 8))
show("godot_member CharacterBody2D.move_and_slide", engine_api.get_member("CharacterBody2D", "move_and_slide"))
show("godot_class Timer (first 700 chars)", engine_api.get_class("Timer")[:700])
show("capsule_catalog effect_types (first 700)", catalogs.catalog("effect_types")[:700])
show("capsule_catalog damage_types", catalogs.catalog("damage_types"))
show("capsule_catalog sticker_bases (first 400)", catalogs.catalog("sticker_bases")[:400])
show("capsule_find_files heroes *.tscn", project_ground.find_files("heroes", "*.tscn", 15))
show("capsule_convention('signal') (first 500)", project_ground.convention("signal")[:500])

tools = asyncio.run(mcp.list_tools())
show("REGISTERED MCP TOOLS", "\n".join(f"- {t.name}" for t in tools))
