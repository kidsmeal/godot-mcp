"""godot-mcp init — scaffold a Godot project for the godot-grounding MCP.

    python -m godot_mcp.init [PROJECT_PATH]   (default: cwd)

Writes <project>/godot-mcp.toml (if absent, with detected defaults) and renders the
agent-mode files (godot-editor subagent, /godot skill, Codex mirror) into the project's
.claude/ and .codex/. Idempotent: keeps an existing godot-mcp.toml.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TPL = REPO / "agent" / "templates"

_DOC_CANDIDATES = {
    "AGENTS": "AGENTS.md", "CLAUDE": "CLAUDE.md", "README": "README.md",
    "INDEX": "docs/INDEX.md", "GLOSSARY": "docs/GLOSSARY.md", "ROADMAP": "docs/ROADMAP.md",
}

_DEFAULT_TOML = '''# godot-grounding MCP — project profile.
[project]
name = "__NAME__"
index_doc = "INDEX"

[engine]
godot_bin = "godot"

[tests]
suite = "res://tests/run_all.tscn"
# integration = "res://tests/run_integration.tscn"
# framework = "custom"   # or "gut" / "gdunit4" (non-custom => pass/fail by exit code)

# Docs exposed by project_convention (friendly name -> path relative to project root)
[docs]
__DOCS__

# Catalogs parsed from source for project_catalog (1 capture group = key list;
# 2 groups = "key - value"). `autoloads` is built in. Example:
# [[catalog]]
# name = "effect_types"
# file = "systems/upgrades/registry.gd"
# pattern = 'register_effect_processor\\(\\s*&"([^"]+)"'

# Linter typo check: flag a use (use_pattern) that is a near-miss of any project-wide
# registration (valid_pattern). Example:
# [[lint_catalog_ref]]
# use_pattern = 'effect_type"?\\s*[:=]\\s*&?"([^"]+)"'
# valid_pattern = 'register_effect_processor\\(\\s*&"([^"]+)"'
'''


def _project_name(root: Path) -> str:
    try:
        pg = (root / "project.godot").read_text(encoding="utf-8", errors="replace")
        m = re.search(r'config/name="([^"]*)"', pg)
        return m.group(1) if m and m.group(1) else root.name
    except Exception:
        return root.name


def _detect_docs(root: Path) -> str:
    found = {k: v for k, v in _DOC_CANDIDATES.items() if (root / v).exists()}
    if not found:
        return '# AGENTS = "AGENTS.md"'
    return "\n".join(f'{k} = "{v}"' for k, v in found.items())


def _render(tpl: Path, name: str, path: str) -> str:
    return tpl.read_text(encoding="utf-8").replace("{{PROJECT_NAME}}", name).replace("{{PROJECT_PATH}}", path)


def _venv_python() -> Path:
    sub, exe = ("Scripts", "python.exe") if os.name == "nt" else ("bin", "python")
    return REPO / ".venv" / sub / exe


def _write_mcp_json(root: Path, godot_bin: str) -> Path | str:
    """Create or merge the project's .mcp.json with the godot-grounding server entry.

    Returns the Path on success.  Returns an error string (and leaves the file
    byte-identical) when the existing .mcp.json is corrupt or has a non-dict
    top level — never silently clobbers other MCP server registrations.
    """
    mcp_path = root / ".mcp.json"
    entry = {
        "command": str(_venv_python()),
        "args": [str(REPO / "main.py")],
        "env": {"GODOT_PROJECT": str(root), "GODOT_BIN": godot_bin},
    }
    data: dict = {}
    if mcp_path.exists():
        raw = mcp_path.read_text(encoding="utf-8-sig")
        if not raw.strip():
            return f"Refused: {mcp_path} is empty or blank — fix or delete it first"
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            return f"Refused: {mcp_path} contains invalid JSON ({exc}); fix it first to avoid losing other server registrations"
        if not isinstance(parsed, dict):
            return f"Refused: {mcp_path} top-level value is {type(parsed).__name__}, expected an object; fix it first"
        data = parsed

    mcp_servers = data.get("mcpServers")
    if mcp_servers is not None and not isinstance(mcp_servers, dict):
        return f"Refused: {mcp_path} 'mcpServers' value is {type(mcp_servers).__name__}, expected an object; fix it first"
    data.setdefault("mcpServers", {})["godot-grounding"] = entry
    mcp_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
    return mcp_path


def _uninstall(root: Path) -> int:
    removed: list[str] = []
    mcp_path = root / ".mcp.json"
    if mcp_path.exists():
        try:
            data = json.loads(mcp_path.read_text(encoding="utf-8-sig"))
        except Exception:
            data = None
        if isinstance(data, dict) and "godot-grounding" in data.get("mcpServers", {}):
            del data["mcpServers"]["godot-grounding"]
            if data.get("mcpServers"):
                mcp_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
                removed.append(".mcp.json (removed godot-grounding entry)")
            else:
                mcp_path.unlink()
                removed.append(".mcp.json (deleted — no other servers)")
    for rel in (".claude/agents/godot-editor.md", ".codex/agents/godot-editor.toml", "godot-mcp.toml"):
        p = root / rel
        if p.exists():
            p.unlink()
            removed.append(rel)
    skill = root / ".claude" / "skills" / "godot"
    if skill.exists():
        shutil.rmtree(skill)
        removed.append(".claude/skills/godot/")
    # C31: remove the bridge addon so the TCP-listening plugin is not left installed
    addon_dir = root / "addons" / "godot_grounding_bridge"
    if addon_dir.exists():
        shutil.rmtree(addon_dir)
        removed.append("addons/godot_grounding_bridge/")
        print("  Note: re-open Godot to deactivate the plugin and remove the editor_plugins entry from project.godot.")

    print(f"Uninstalled godot-grounding from {root}:")
    for r in removed:
        print(f"  - {r}")
    if not removed:
        print("  (nothing to remove)")
    print("\nReload Claude Code / reconnect to drop the server. The godot-mcp repo itself is untouched.")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    uninstall = "--uninstall" in argv
    positionals = [a for a in argv if not a.startswith("-")]
    root = (Path(positionals[0]) if positionals else Path.cwd()).resolve()
    if uninstall:
        return _uninstall(root)
    if not (root / "project.godot").exists():
        print(f"! warning: no project.godot at {root} — is this a Godot project root?")
    toml_path = root / "godot-mcp.toml"
    name = _project_name(root)
    godot_bin = "godot"
    if toml_path.exists():
        try:
            import tomllib
            data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
            name = data.get("project", {}).get("name") or name
            godot_bin = data.get("engine", {}).get("godot_bin") or godot_bin
        except Exception:
            pass
        print(f"= kept existing {toml_path.name}")
    else:
        toml_path.write_text(_DEFAULT_TOML.replace("__NAME__", name).replace("__DOCS__", _detect_docs(root)), encoding="utf-8", newline="\n")
        print(f"+ wrote {toml_path.name}")
    print(f"Project: {name}  ({root})")

    targets = {
        TPL / "godot-editor.md.tmpl": root / ".claude" / "agents" / "godot-editor.md",
        TPL / "SKILL.md.tmpl": root / ".claude" / "skills" / "godot" / "SKILL.md",
        TPL / "godot-editor.toml.tmpl": root / ".codex" / "agents" / "godot-editor.toml",
    }
    for tpl, dst in targets.items():
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(_render(tpl, name, str(root)), encoding="utf-8", newline="\n")
        print(f"+ wrote {dst.relative_to(root)}")

    mcp_result = _write_mcp_json(root, godot_bin)
    if isinstance(mcp_result, str):
        print(f"! {mcp_result}")
    else:
        print(f"+ wrote/merged {mcp_result.name} (godot-grounding server)")

    addon_src = REPO / "addon" / "godot_grounding_bridge"
    if addon_src.exists():
        addon_dst = root / "addons" / "godot_grounding_bridge"
        # C31: use copytree so subdirectories are not silently dropped
        if addon_dst.exists():
            shutil.rmtree(addon_dst)
        shutil.copytree(str(addon_src), str(addon_dst))
        print(f"+ wrote {addon_dst.relative_to(root)}/  (optional: enable in Project > Project Settings > Plugins for the live editor bridge)")

    print("\nNext:")
    print("  1. Dump the engine API if you haven't:  setup.ps1   (or scripts/dump_api.ps1).")
    print("  2. Reload Claude Code / reconnect the MCP server, then try /godot.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
