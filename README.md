# godot-grounding MCP

A Model Context Protocol server that grounds an AI agent in **exact, version-pinned
Godot API** and a **specific project's own conventions** — built for Godot 4.6 and
tuned to the Capsule Castle project, but pointable at any Godot project.

This is Phases 1–3 of a larger plan (grounding → validate wrappers → convention-linted
file ops → a `godot-editor` agent mode → optional live editor bridge). It grounds,
validates (headless tests), and makes parse-checked, convention-linted GDScript edits —
rolling back any write that doesn't parse.

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
| `godot_run_tests(filter, integration)` | Headless test suite → structured pass/fail (files, tests, assertions, failures) |
| `godot_check(script_path)` | Parse-check one GDScript without running it (`--check-only`) |
| `godot_run_script(script_path)` | Run a standalone headless dev/validator script |
| `godot_verify_enemies()` | Run the project's enemy validator script |
| `godot_lint(script_path)` | Lint one file against AGENTS.md conventions (typing, signals, naming, paths) |
| `godot_lint_source(source)` | Lint a GDScript string before writing it |
| `godot_write_script(path, content)` | Write a full file with parse-check + rollback; reports lint |
| `godot_patch_script(path, old, new)` | Exact-match patch with parse-check + rollback |

The validation tools capture output via Godot's `--log-file` (robust on the Windows
GUI build) and read pass/fail from the process exit code. The edit tools never leave the
project in a non-parsing state — they back up, write, run `--check-only`, and roll back on
failure. Lint findings are reported but non-blocking by default (`enforce_conventions=True`
refuses writes with convention errors).

The linter runs on gdtoolkit's GDScript AST (multi-line-accurate, with a regex fallback for
the rare unparseable file), supports `# lint: ignore` / `# lint: ignore=rule,rule`, and
includes a catalog-aware check that flags `effect_type` keys that look like typos of
registered ones. Validated at 0 false positives across the 615-file project codebase.

## Setup

```powershell
cd C:\Users\atk67\Documents\godot-mcp
py -m venv .venv
.\.venv\Scripts\python -m pip install -U pip -r requirements.txt   # mcp + gdtoolkit
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
