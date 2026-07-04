# Shipped — godot-grounding MCP

What's live in the server today, with a one-line descriptor each. The connector's
loop is **ground → linted edit → test-to-confirm**, driven by a per-project
`godot-mcp.toml` profile so it works on any Godot project.

## Tools (30)

### Engine grounding — exact, version-pinned Godot API
| Tool | What it does |
|---|---|
| `godot_version()` | Reports the Godot version the API is pinned to + the project's name/features. |
| `godot_doctor()` | Health check: API dump present & version-matched, Godot binary resolvable, gdtoolkit installed, profile paths exist. |
| `godot_class(name, include_inherited=False, full_docs=False)` | Full class API (methods, properties, signals, enums, constants) + **first-sentence** doc descriptions (`full_docs=True` for the fuller, char-capped text). `include_inherited=True` also lists base-class members. Char-budgeted with a drill-down tail. |
| `godot_member(class_name, member, full_docs=False)` | Exact signature of one member + its **first-sentence** doc description (`full_docs=True` for the fuller text). **Resolves inherited members** — walks the base-class chain and labels the origin class. |
| `godot_search(query, limit=25)` | Keyword search across engine classes, **built-ins** (e.g. `Color.from_hsv`), **singletons**, and `Class.method`, exact/prefix-ranked so the best match isn't buried. |

### Project grounding — the target project's own values
| Tool | What it does |
|---|---|
| `project_convention(topic)` | Searches the project's convention/design docs (from the profile) for a topic. |
| `project_catalog(kind)` | Lists a project catalog parsed straight from source (e.g. `effect_types`), plus built-in `autoloads`. |
| `project_index()` | Returns the project's configured codebase-map / index doc. |
| `project_input_actions()` | Lists the project's input actions (from `project.godot` `[input]`) + the built-in `ui_*` set — grounds `Input.is_action_*` strings. |
| `project_setting(name, resolve=False)` | Reads a `project.godot` setting by dotted key; `resolve=True` applies default-overrides via a headless probe (degrades gracefully). |
| `project_classes()` | Maps every `class_name` → `res://path` across the project's `.gd`, cached on the file signature. |
| `project_layers()` | Named physics / render / navigation / avoidance layers from `[layer_names]`, grouped by category. |
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
| `editor_ping()` | Checks the bridge connection / reports the running editor version. |
| `editor_run_game(scene)` | Plays the `main` or `current` scene in the open editor. |
| `editor_stop_game()` | Stops the running scene. |
| `editor_scene_tree()` | Returns the live node tree of the scene open in the editor. |
| `editor_open_scene(path)` | Opens a scene in the editor; validates the `res://` path is in-project before sending. |

---

## Shipped milestones

### Hardening & correctness track (current — driven through the Gantry pipeline)
- **Review hardening pass** — centralized `config.resolve_project_path()` helper, BBCode-stripped + length-capped engine doc descriptions, env-driven editor-bridge port (`GODOT_BRIDGE_PORT` on both sides), and a stale tool-name fix (`capsule_convention` → `project_convention`).
- **Phase 1 — Path containment** — every file-taking tool now routes through one resolver and **refuses out-of-root paths before any read or Godot launch**, closing confirmed-live leaks (`godot_lint`/`godot_check`/`godot_run_script`/`godot_lint_scene` operated on outside-project paths; `patch_script`/`auto_fix` read outside content before refusing). Stood up **pytest** with 27 containment regression tests.
- **Phase 1B — Probe/validation harness hardening** — the validator harness runs from the plugin's own `data/` dir by absolute path (zero project-root writes), added the sanctioned **`godot_validate`** tool + a leak-proof `run_temp_probe` (cleans its temp `.gd`/`.gd.uid` even on a crash), and relocated deliberate-broken linter fixtures into the plugin. Stops temp scripts from leaking into tracked game projects.
- **Phase 2 — Engine grounding correctness** — `godot_member` resolves **inherited** members (walks the base chain, labels the origin); `godot_class` gains `include_inherited`; `godot_search` now covers **built-ins and singletons**. (72 tests green.) `b47973f`
- **Phase 3 — Profile robustness** — a malformed `godot-mcp.toml` surfaces as a loud `doctor` FAIL instead of a crash; catalog specs are crash-proofed. `d13f3a8`
- **Phase 4 — Toolchain formalization** — added **ruff + mypy**, wired CI, and pinned the tool surface with an **exact-roster `ci_smoke` assertion** (a dropped/renamed tool now fails CI). `bbf5df8`
- **Phase 5 — Feature F: grounding surfaces** — `project_input_actions` / `project_setting` / `project_classes` / `project_layers`, plus an input-action typo-lint. `feace6d` (+ audit fixes A1–A6 `b0bbabd`). (142 tests green.)
- **Phase 6 — Bridge hardening** — per-client framing + byte caps, an **auth token** on the command channel, error classification, and `protocol`/`bridge_version` in `ping` + a doctor check (audit bucket B). `0e5cb0d` (162 tests green.)
- **Phase 6.5 — Audit hardening batch (bucket C)** — edit-path integrity (rollback try/except, CRLF preserve, UTF-8 strictness, string-aware autofix), **env-failure-vs-parse-failure verdicts** (retry elimination), validation false-FAIL fixes, crash class (profile shape validation, `.mcp.json` clobber safety), and grounding-data correctness (utility/global-enum indexing + a doctor binary-version drift check, version-keyed doc cache, offline circuit breaker, search ranking). Six phases `96677cd` → `3f381ab` → `f196fed` → `aecb79e` → `b93e79c` → `ea2fc31`. (280 tests green.)
- **Phase 6.6 — Tool-surface settle** — settled the permanent naming families (`godot_*` engine + validate/edit/test, `project_*` project grounding, **`editor_*` live editor bridge**) by renaming the 5 bridge tools `godot_*`→`editor_*` across every surface; added the FastMCP **`instructions=` block** carrying shared semantics once (res:// rules, the "Refused" containment shape, `# lint: ignore` syntax, the ground→edit→confirm loop) + a docstring slim pass; and **response caps** — `godot_class`/`godot_member` return first-sentence doc descriptions by default with a `full_docs=True` param. `1bc6b96` → `56f3a4d` → `aa9c09e` → `42c0a37` → `c62426f`. (301 tests green, ruff + mypy clean.)

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
See `NOW.md` for the live cursor. Next up: the **procgen tool suite** (`docs/design/procgen-tools.md` + `.plan.md`) — a new `procgen_*` family for headless tileset build + biome island generation (`procgen_tileset_build`, `procgen_terrain_audit`, `procgen_worldgen_preview`, `procgen_island_preview`, `procgen_chunk_lint`, `procgen_gen_smoke`); plan phases 0–3 are self-contained here, 4–6 gated on the game repo's dump hooks. Then **Phase 7** (runtime loop: `editor_run_game_headless` / `godot_screenshot` / `godot_validate_scene_load`) and **Phase 8** (scene authoring, gated).
