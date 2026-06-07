# Shipped — godot-grounding MCP

What's live in the server today, with a one-line descriptor each. The connector's
loop is **ground → linted edit → test-to-confirm**, driven by a per-project
`godot-mcp.toml` profile so it works on any Godot project.

## Tools (26)

### Engine grounding — exact, version-pinned Godot API
| Tool | What it does |
|---|---|
| `godot_version()` | Reports the Godot version the API is pinned to + the project's name/features. |
| `godot_doctor()` | Health check: API dump present & version-matched, Godot binary resolvable, gdtoolkit installed, profile paths exist. |
| `godot_class(name, include_inherited=False)` | Full class API (methods, properties, signals, enums, constants) + doc descriptions. `include_inherited=True` also lists base-class members. |
| `godot_member(class_name, member)` | Exact signature of one member + its doc description. **Resolves inherited members** — walks the base-class chain and labels the origin class. |
| `godot_search(query, limit=25)` | Keyword search across engine classes, **built-ins** (e.g. `Color.from_hsv`), **singletons**, and `Class.method`. |

### Project grounding — the target project's own values
| Tool | What it does |
|---|---|
| `project_convention(topic)` | Searches the project's convention/design docs (from the profile) for a topic. |
| `project_catalog(kind)` | Lists a project catalog parsed straight from source (e.g. `effect_types`), plus built-in `autoloads`. |
| `project_index()` | Returns the project's configured codebase-map / index doc. |
| `project_find_files(subdir, pattern)` | Reliable recursive `res://` file listing (avoids the Windows glob miss); containment-guarded. |
| `project_find_refs(symbol, kind)` | Classified references to an identifier across all `.gd` (def / call / type / member / extends / ref); comment- & string-aware. |
| `project_scene(scene_path)` | Summarizes a `.tscn` without opening the editor: dependencies, node tree, attached scripts, signal connections. |
| `godot_lint_scene(scene_path)` | Lints a `.tscn` for silent breakage: missing `ext_resource` paths, `.godot/imported` refs, type-as-name nodes. |

### Convention-linted, parse-checked edits — never leaves the project non-parsing
| Tool | What it does |
|---|---|
| `godot_lint(script_path)` | Lints an existing GDScript against the project's conventions (typing, signals, naming, paths, catalog-key typos). |
| `godot_lint_source(source)` | Same lint, on a GDScript string before it's written. |
| `godot_write_script(path, content)` | Writes a full file: backs up → writes → `--check-only` → **rolls back on any parse error**; reports lint. |
| `godot_patch_script(path, old, new)` | Exact-match substring patch with the same parse-check + rollback. |
| `godot_fix_script(path)` | Applies safe mechanical lint fixes (`:=`, `-> void`) and re-verifies through the rollback writer. |

### Headless validation — the feedback loop
| Tool | What it does |
|---|---|
| `godot_run_tests(filter, integration)` | Runs the project's headless test suite → structured pass/fail (files, tests, assertions, failures). |
| `godot_check(script_path)` | Parse-checks one GDScript without running it (`--check-only`); containment-guarded. |
| `godot_validate(script_path)` | **Validates with autoloads registered** (boots a SceneTree) — catches autoload-reference errors `--check-only` misses. Runs from the plugin's own harness, never copies into the project. |
| `godot_run_script(script_path)` | Runs a headless `SceneTree`/`MainLoop` script (validators/generators); containment-guarded. |

### Live editor bridge — drives an open Godot editor (optional addon)
| Tool | What it does |
|---|---|
| `godot_editor_ping()` | Checks the bridge connection / reports the running editor version. |
| `godot_run_game(scene)` | Plays the `main` or `current` scene in the open editor. |
| `godot_stop_game()` | Stops the running scene. |
| `godot_editor_scene_tree()` | Returns the live node tree of the scene open in the editor. |
| `godot_open_scene(path)` | Opens a scene in the editor; validates the `res://` path is in-project before sending. |

---

## Shipped milestones

### Hardening & correctness track (current — driven through the Gantry pipeline)
- **Review hardening pass** — centralized `config.resolve_project_path()` helper, BBCode-stripped + length-capped engine doc descriptions, env-driven editor-bridge port (`GODOT_BRIDGE_PORT` on both sides), and a stale tool-name fix (`capsule_convention` → `project_convention`).
- **Phase 1 — Path containment** — every file-taking tool now routes through one resolver and **refuses out-of-root paths before any read or Godot launch**, closing confirmed-live leaks (`godot_lint`/`godot_check`/`godot_run_script`/`godot_lint_scene` operated on outside-project paths; `patch_script`/`auto_fix` read outside content before refusing). Stood up **pytest** with 27 containment regression tests.
- **Phase 1B — Probe/validation harness hardening** — the validator harness runs from the plugin's own `data/` dir by absolute path (zero project-root writes), added the sanctioned **`godot_validate`** tool + a leak-proof `run_temp_probe` (cleans its temp `.gd`/`.gd.uid` even on a crash), and relocated deliberate-broken linter fixtures into the plugin. Stops temp scripts from leaking into tracked game projects.
- **Phase 2 — Engine grounding correctness** — `godot_member` resolves **inherited** members (walks the base chain, labels the origin); `godot_class` gains `include_inherited`; `godot_search` now covers **built-ins and singletons**. (72 tests green.)

### Foundation (prior)
- **Phases 1–3** — engine + project grounding; headless validation wrappers; convention-linted, parse-checked GDScript edits.
- **Linter** — gdtoolkit AST backend + catalog-aware typo check + `# lint: ignore` suppression (0 false positives across the 615-file Capsule Castle codebase).
- **Genericization** — per-project `godot-mcp.toml` profile + `project_*` tools + an `init` scaffolder, so the connector is reusable across Godot projects.
- **Distribution** — one-command `setup.ps1`, a one-liner installer (PowerShell + `install.sh`), uninstall, and a CI smoke workflow.
- **Agent mode** — a `godot-editor` subagent + a `/godot` skill (with a Codex mirror) wiring the tools into the ground → linted edit → test loop.
- **Feature A** — `godot_doctor` + engine doc descriptions.
- **Feature B** — scene tooling (`project_scene` + `godot_lint_scene`).
- **Feature C** — `godot_fix_script` (safe mechanical lint autofix).
- **Feature D** — `project_find_refs` (comment/string-aware reference finder).
- **Feature E** — live editor bridge (EditorPlugin + 5 `godot_editor`/`run`/`open` tools).
- **Robustness** — `valid_keys` mtime-signature cache + per-framework test parsing.

---

## In flight (planned, not yet shipped)
See `docs/design/feature-batch-fgh.plan.md`. Next up: **Phase 3** (profile robustness — malformed `godot-mcp.toml` becomes a loud `doctor` FAIL), then Phase 4 (ruff/mypy/CI), Phase 5 (grounding surfaces: `project_input_actions` / `project_setting` / `project_classes` / `project_layers`), Phase 6 (bridge hardening), Phase 7 (runtime loop: `godot_run_game_headless` / `godot_screenshot`), Phase 8 (scene authoring, gated).
