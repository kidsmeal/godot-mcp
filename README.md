# godot-grounding MCP

A Model Context Protocol server that grounds an AI agent in **exact, version-pinned
Godot API** and a **specific project's own conventions** — built for Godot 4.6 and
tuned to the Capsule Castle project, but pointable at any Godot project.

This is Phase 1 of a larger plan (grounding → validate wrappers → convention-linted
file ops → a `godot-editor` agent mode → optional live editor bridge). It is
read-only: it answers questions, it does not yet edit the project.

## Why

Generic models hallucinate old Godot APIs (3.x renames, `yield`→`await`,
`KinematicBody`→`CharacterBody`) and invent project values (effect_type / sticker
keys) that don't exist. This server removes both failure modes by serving:

- **Engine grounding** from `extension_api.json` dumped from *your* engine build.
- **Project grounding** from the project's `AGENTS.md`, `docs/INDEX.md`, and the
  catalogs parsed straight out of GDScript source.

## Tools

| Tool | What it grounds |
|---|---|
| `godot_version` | Engine version the API is pinned to + project features |
| `godot_class(name)` | Full class API: methods, properties, signals, enums, constants |
| `godot_member(class_name, member)` | One exact signature |
| `godot_search(query, limit)` | Find classes / `Class.method` by keyword |
| `capsule_convention(topic)` | Search AGENTS.md / CLAUDE.md / design guides |
| `capsule_catalog(kind)` | `effect_types`, `sticker_bases`, `damage_types`, `autoloads`, `all` |
| `capsule_index()` | The codebase map (`docs/INDEX.md`) |
| `capsule_find_files(subdir, pattern)` | Windows-glob-safe `res://` file listing |

## Setup

```powershell
cd C:\Users\atk67\Documents\godot-mcp
py -m venv .venv
.\.venv\Scripts\python -m pip install -U pip mcp
.\scripts\dump_api.ps1          # writes data\extension_api.json (needs `godot` on PATH)
```

## Register with Claude Code

Copy `.mcp.json.example` to `.mcp.json` (or merge into your client config), adjust
paths if needed, then restart the client. Override the target project per-run with
the `GODOT_PROJECT` env var.

## Config (env vars)

| Var | Default |
|---|---|
| `GODOT_PROJECT` | `C:\Users\atk67\Documents\capsulecastle` |
| `GODOT_BIN` | `godot` |
| `GODOT_MCP_DATA` | `<repo>\data` |
