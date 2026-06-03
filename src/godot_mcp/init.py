"""godot-mcp init — scaffold a Godot project for the godot-grounding MCP.

    python -m godot_mcp.init [PROJECT_PATH]   (default: cwd)

Writes <project>/godot-mcp.toml (if absent, with detected defaults) and renders the
agent-mode files (godot-editor subagent, /godot skill, Codex mirror) into the project's
.claude/ and .codex/. Idempotent: keeps an existing godot-mcp.toml.
"""
from __future__ import annotations

import re
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


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    root = (Path(argv[0]) if argv else Path.cwd()).resolve()
    if not (root / "project.godot").exists():
        print(f"! warning: no project.godot at {root} — is this a Godot project root?")
    toml_path = root / "godot-mcp.toml"
    name = _project_name(root)
    if toml_path.exists():
        try:
            import tomllib
            name = tomllib.loads(toml_path.read_text(encoding="utf-8")).get("project", {}).get("name") or name
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

    print("\nNext:")
    print("  1. Add the godot-grounding server to this project's .mcp.json (set GODOT_PROJECT to this path).")
    print("  2. Dump the engine API:  scripts/dump_api.ps1   (needs `godot` on PATH).")
    print("  3. Reload Claude Code / reconnect MCP, then try /godot.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
