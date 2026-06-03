# Installing the Godot agent mode

Canonical, version-controlled copies of the agent-mode pieces live here. Install
them into the target project (Capsule Castle) so Claude Code / Codex can use them.

## What's here
| File | Installs to | Purpose |
|---|---|---|
| `claude/agents/godot-editor.md` | `<project>/.claude/agents/` | The `godot-editor` subagent |
| `claude/skills/godot/SKILL.md` | `<project>/.claude/skills/godot/` | The `/godot` skill (Godot mode) |
| `codex/agents/godot-editor.toml` | `<project>/.codex/agents/` | Codex mirror of the subagent |

## Install (PowerShell, from this repo)
```powershell
$P = "C:\Users\atk67\Documents\capsulecastle"
New-Item -ItemType Directory -Force "$P\.claude\agents","$P\.claude\skills\godot","$P\.codex\agents" | Out-Null
Copy-Item agent\claude\agents\godot-editor.md      "$P\.claude\agents\"        -Force
Copy-Item agent\claude\skills\godot\SKILL.md       "$P\.claude\skills\godot\"   -Force
Copy-Item agent\codex\agents\godot-editor.toml     "$P\.codex\agents\"          -Force
```

## After installing
1. Reload Claude Code in the project (or `/mcp` reconnect) so it picks up the new
   subagent + skill.
2. The agent mode depends on the `godot-grounding` MCP server being registered
   (`.mcp.json`) and connected.
3. Try it: `/godot` then a task, or ask Claude to "use the godot-editor subagent to …".

## Prerequisites
- `godot-grounding` MCP server registered and connected (see the repo README).
- `godot` on PATH and `data/extension_api.json` dumped (`scripts/dump_api.ps1`).
