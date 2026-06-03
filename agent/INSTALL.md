# Installing the Godot agent mode

**Easiest:** from the repo root, `.\setup.ps1 -Project "C:\path\to\your\project"` does
everything below (and the repo bootstrap). The manual path is documented here for reference.

`templates/` holds the source agent-mode files. `python -m godot_mcp.init` renders them into a
target project (filling in name + path), scaffolds the profile, and writes/merges `.mcp.json`.

## Install into a project (manual)
```powershell
$env:PYTHONPATH = "C:\Users\atk67\Documents\godot-mcp\src"
& C:\Users\atk67\Documents\godot-mcp\.venv\Scripts\python.exe -m godot_mcp.init "C:\path\to\your\godot\project"
```

This writes (idempotently — an existing `godot-mcp.toml` is kept):
| File | Purpose |
|---|---|
| `<project>/godot-mcp.toml` | The profile (name, tests, docs, catalogs, lint refs) |
| `<project>/.mcp.json` | Registers the `godot-grounding` server (merged if present) |
| `<project>/.claude/agents/godot-editor.md` | The `godot-editor` subagent |
| `<project>/.claude/skills/godot/SKILL.md` | The `/godot` skill |
| `<project>/.codex/agents/godot-editor.toml` | Codex mirror of the subagent |

## After installing
1. Register the `godot-grounding` MCP server in `<project>/.mcp.json` (set `GODOT_PROJECT`
   to the project path). See the repo `.mcp.json.example`.
2. Dump the engine API for the project's Godot version: `scripts/dump_api.ps1`
   (needs `godot` on PATH).
3. Reload Claude Code / `/mcp` reconnect, then `/godot` or invoke the `godot-editor` subagent.

## Tuning
Everything project-specific lives in `<project>/godot-mcp.toml` — edit it to declare your
test scenes, the docs `project_convention` exposes, the catalogs `project_catalog` parses,
and the linter's catalog typo cross-references. The agent text itself is generic; re-run
`init` after changing the project name to re-render it.
