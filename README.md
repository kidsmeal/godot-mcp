# godot-grounding MCP

A Model Context Protocol server that grounds an AI agent in **exact, version-pinned
Godot API** and a **project's own conventions/catalogs**. Reusable across Godot projects
via a per-project profile (`godot-mcp.toml`); the included profile targets Capsule Castle.

This is Phases 1–3 + the agent mode of a larger plan (grounding → validate wrappers →
convention-linted file ops → a `godot-editor` agent mode → optional live editor bridge).
It grounds, validates (headless tests), and makes parse-checked, convention-linted GDScript
edits — rolling back any write that doesn't parse.

## Install (one-liner)

PowerShell — clones the repo to `%USERPROFILE%\godot-mcp` and bootstraps everything (venv,
deps, Godot on PATH, engine-API dump):

```powershell
iwr -useb https://raw.githubusercontent.com/kidsmeal/godot-mcp/main/install.ps1 | iex
```

Onboard a Godot project in the same step:

```powershell
$env:GODOT_MCP_PROJECT="C:\path\to\your\game"; iwr -useb https://raw.githubusercontent.com/kidsmeal/godot-mcp/main/install.ps1 | iex
```

**macOS / Linux** (needs `godot` on PATH, or set `GODOT_BIN`):

```bash
curl -fsSL https://raw.githubusercontent.com/kidsmeal/godot-mcp/main/install.sh | bash
# onboard in one step:  GODOT_MCP_PROJECT=/path/to/game curl -fsSL .../install.sh | bash
```

Then reload Claude Code / reconnect the MCP server in the project and use `/godot`.
Already cloned? Use **Setup** below.

## Why

Generic models hallucinate old Godot APIs (3.x renames, `yield`→`await`,
`KinematicBody`→`CharacterBody`) and invent project values (effect_type / sticker
keys) that don't exist. This server removes both failure modes by serving:

- **Engine grounding** from `extension_api.json` dumped from *your* engine build.
- **Project grounding** from the docs and catalogs declared in the project's
  `godot-mcp.toml` profile, parsed straight out of source.

## Tools

| Tool | What it grounds |
|---|---|
| `godot_version` | Engine version the API is pinned to + project features |
| `godot_doctor` | Health check: API dump/version, Godot binary, gdtoolkit, profile paths |
| `godot_class(name, include_inherited)` | Full class API **+ doc descriptions**: methods, properties, signals, enums, constants. `include_inherited=True` also lists members from base classes |
| `godot_member(class_name, member)` | One exact signature **+ its doc description**; resolves **inherited** members (walks the base-class chain, labels the origin) |
| `godot_search(query, limit)` | Find classes, built-ins (e.g. `Color.from_hsv`), singletons, and `Class.method` by keyword |
| `project_convention(topic)` | Search the profile's docs (conventions / design guides) |
| `project_catalog(kind)` | Catalogs from the profile (e.g. `effect_types`, `damage_types`) + `autoloads`, `all` |
| `project_index()` | The configured codebase-map doc |
| `project_find_files(subdir, pattern)` | Windows-glob-safe `res://` file listing |
| `project_find_refs(symbol, kind)` | Classified references to an identifier across all `.gd` (def/call/type/…) |
| `project_input_actions()` | All input actions: project-defined (from `[input]`) + built-in `ui_*` roster |
| `project_setting(name, resolve)` | A project setting value by dotted key (e.g. `application/config/name`); `resolve=True` uses a Godot probe |
| `project_classes()` | All `class_name` declarations in the project, mapped to their `res://` path |
| `project_layers()` | Named physics, render, navigation, and avoidance layers from `[layer_names]` |
| `project_scene(scene_path)` | Summarize a `.tscn`: deps, node tree, scripts, connections |
| `godot_lint_scene(scene_path)` | Lint a `.tscn`: missing ext_resources, `.godot/imported`, type-as-name |
| `godot_run_tests(filter, integration)` | Headless test suite → structured pass/fail (files, tests, assertions, failures) |
| `godot_check(script_path)` | Parse-check one GDScript without running it (`--check-only`) |
| `godot_validate(script_path)` | Validate a GDScript with autoloads registered (SceneTree boot; catches autoload-reference errors `--check-only` misses) |
| `godot_run_script(script_path)` | Run a headless SceneTree/MainLoop script (validators/generators) |
| `godot_lint(script_path)` | Lint one file against AGENTS.md conventions (typing, signals, naming, paths) |
| `godot_lint_source(source)` | Lint a GDScript string before writing it |
| `godot_write_script(path, content)` | Write a full file with parse-check + rollback; reports lint |
| `godot_patch_script(path, old, new)` | Exact-match patch with parse-check + rollback |
| `godot_fix_script(path)` | Apply safe mechanical lint fixes (`:=`, `-> void`) + re-verify |

The validation tools capture output via Godot's `--log-file` (robust on the Windows
GUI build) and read pass/fail from the process exit code. The edit tools never leave the
project in a non-parsing state — they back up, write, run `--check-only`, and roll back on
failure. Lint findings are reported but non-blocking by default (`enforce_conventions=True`
refuses writes with convention errors).

The linter runs on gdtoolkit's GDScript AST (multi-line-accurate, with a regex fallback for
the rare unparseable file), supports `# lint: ignore` / `# lint: ignore=rule,rule`, and
includes a catalog-aware check that flags catalog keys (per the profile's `lint_catalog_ref`)
that look like typos of registered ones. Validated at 0 false positives across the 615-file
Capsule Castle codebase.

`godot_class` / `godot_member` enrich signatures with the engine's official **doc
descriptions**, fetched lazily per class from the matching Godot version tag and cached under
`data/godot_docs/` (offline after first fetch; set `GODOT_MCP_DOCS=0` to disable).

## Setup

One command bootstraps the repo (venv, deps, finds Godot and shims it onto PATH, dumps the
engine API) **and** onboards a project (profile + `/godot` agent mode + `.mcp.json`):

```powershell
cd C:\Users\atk67\Documents\godot-mcp
.\setup.ps1 -Project "C:\path\to\your\godot\project"
```

Flags: `-GodotBin <path>` if Godot isn't auto-found, `-Force` to re-dump the API. Idempotent —
safe to re-run. Omit `-Project` to just bootstrap the repo. Afterwards, reload Claude Code /
reconnect the MCP server in the project and use `/godot`.

## Agent mode

A **`godot-editor` subagent** + a **`/godot` skill** (with a Codex mirror) wire these tools
into one specialized loop: **ground → linted edit → test-to-confirm**. The subagent grounds
every engine API and project value, edits only through the linted/parse-checked writer, and
won't report done until the relevant headless tests pass. Sources live in `agent/templates/`;
`init` renders them (with the project's name/path) into the project's `.claude/` + `.codex/`.
See `agent/INSTALL.md`.

## Use on another Godot project

Re-run setup with a different project — each is onboarded independently:

```powershell
.\setup.ps1 -Project "C:\path\to\another\project"
```

Everything project-specific — name, test scenes, docs, catalogs, linter cross-refs — lives in
that project's `godot-mcp.toml`; the agent mode and `.mcp.json` are generated for you. (To
scaffold without re-bootstrapping the repo: `python -m godot_mcp.init <project>`.)

## Uninstall

Remove the integration from a project — deletes the agent files + `godot-mcp.toml` and removes
the `godot-grounding` entry from its `.mcp.json` (other MCP servers preserved; the repo is
untouched):

```powershell
.\setup.ps1 -Uninstall -Project "C:\path\to\your\game"
```

## Live editor bridge (optional)

`init` installs an EditorPlugin (`addons/godot_grounding_bridge/`) into the project. Enable it
in **Project → Project Settings → Plugins**, keep the editor open, and these tools can drive it:

| Tool | Action |
|---|---|
| `editor_ping` | Check the bridge connection / editor version |
| `editor_run_game(scene)` | Play the `main` or `current` scene |
| `editor_stop_game` | Stop the running scene |
| `editor_scene_tree` | Live node tree of the edited scene |
| `editor_open_scene(path)` | Open a scene in the editor |

The bridge listens on `127.0.0.1:9123`. To use a different port, set `GODOT_BRIDGE_PORT`
for **both** the MCP server and the Godot editor (the addon reads it on startup) so the two
agree. Tools degrade gracefully when the editor/addon isn't running.

## Config (env vars)

| Var | Default |
|---|---|
| `GODOT_PROJECT` | `C:\Users\atk67\Documents\capsulecastle` |
| `GODOT_BIN` | profile `[engine] godot_bin`, else `godot` |
| `GODOT_MCP_DATA` | `<repo>\data` |
| `GODOT_MCP_PROFILE` | `<project>\godot-mcp.toml` |
| `GODOT_MCP_DOCS` | `1` (set `0` to disable doc-description fetching) |
| `GODOT_BRIDGE_PORT` | `9123` (live editor bridge — set for both the MCP server and the editor) |
