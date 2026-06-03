# Design: Feature Batch F–H — grounding surfaces, runtime loop, scene authoring

Status: draft (design only — not yet planned or built)
Last commit in series: `a328f6d Feature E: live editor bridge`
Maps to commits by ascending risk: **Phase 0** = path-containment hardening (prerequisite), **F** = grounding surfaces, **G** = runtime loop, **H** = scene authoring.

> **Phase 0 must land before G/H.** A review pass found that only the *write* path enforces project-root containment; reads/lists (`project_find_files`, `scene`, `runner`, `catalogs`) resolve and read ungated paths, and `project_find_files` would even emit absolute paths *outside* the project. G and H add five more path-taking tools (`run_game_headless` scene arg, the scene-mutation `scene_path`/`node_path` args), so the shared resolver should exist first and they inherit containment for free. A partial fix already landed in the hardening pass below (the `config.resolve_project_path()` helper + `project_find_files` adoption); Phase 0 finishes the job.

## Problem

The server's loop is **ground → linted edit → test-to-confirm**, but three holes remain:

1. **Three classes of "project values that exist" are still ungroundable, so the agent invents them.** We ground engine API, profile catalogs, and `autoloads`, but *not* input-map action names, project settings (physics-layer names, etc.), or the project's own `class_name` registry. Writing `Input.is_action_pressed("jertp")`, `set_collision_layer_value(3, true)` against an unnamed layer, or referencing a custom type that doesn't exist are the *same failure mode* the connector was built to kill — we just don't cover them yet.

2. **The agent is blind after running the game.** `godot_run_game` starts a scene in the open editor and returns nothing about the result. There is no headless equivalent of `godot_run_tests` for "play this scene and tell me what errored," and no way to see a frame.

3. **The agent can write scripts but cannot build scenes.** `.tscn` is read-only (`project_scene`, `godot_lint_scene`). Any structural scene change still requires a human in the editor, which breaks the autonomous loop for a large class of tasks (add a node, wire a signal, attach a script).

## Decisions resolved (during grilling)

| # | Decision | Choice |
|---|---|---|
| 1 | Doc scope | All three clusters, **phased by risk** (F → G → H) in one pipeline run |
| 2 | `godot_screenshot` target | **Editor viewport only** (v1). Running-game capture deferred — bridge runs in the editor process; the game is a separate child; `--headless` renders blank |
| 3 | Runtime-error capture | **Headless subprocess** (`godot_run_game_headless`), reusing `runner._run`. The standalone live-stream `godot_runtime_errors` is dropped |
| 4 | Input-action linting | **Typo-check style** — mirror the catalog-ref pattern: flag only near-miss typos of real action names, never bare unknowns (survives runtime-added actions) |
| 5 | `project_setting` source | **File-only + optional `resolve` flag** — parse `project.godot`; `resolve=true` runs a headless `--script` for the true effective value incl. engine defaults |
| 6 | `run_game_headless` termination | **`--quit-after N` frames** (clean exit-0 verdict) **+ subprocess timeout backstop** |
| 7 | `set_property` value encoding | **`str_to_var` Variant strings** (e.g. `"Vector2(4, 8)"`, `&"enemies"`) — no arbitrary-code eval |
| 8 | Scene-mutation rollback | **`EditorUndoRedoManager.undo()` + re-save** on failed reload-check (keeps the open editor authoritative; gives the human a Ctrl+Z) |
| 9 | Scene-mutation target | **`scene_path` param, auto-open** if not already the edited scene |

---

## Design

### Phase 0 — centralize path containment (prerequisite for G/H)

`config.resolve_project_path(path) -> Path` already exists (raises `config.PathEscapeError` on `..`, absolute, or symlink escape) and `project_find_files` now uses it. Phase 0 finishes adoption:

- Replace the duplicate `_abs` / `_res_to_abs` helpers in `edit.py`, `scene.py`, `runner.py` with `config.resolve_project_path`, each mapping `PathEscapeError` to the caller's existing "Refused"/"Not found" string.
- **Contain the tools that hand a path straight to Godot, not just through `_abs`:** `runner.check_script` / `run_script` pass the agent's `script_path` to `--script`; validate it through the resolver before launch. (`run_tests` uses a profile-configured scene — already trusted.)
- Net effect: every file-taking tool, read or write, refuses an out-of-root path identically — so the new G/H tools just call the resolver.

### Phase F — grounding surfaces (cheapest, highest fit, no new infra)

All three are *universal* to every Godot project (parsed from `project.godot` / `.gd` source), so — like the built-in `autoloads` catalog — they need **no profile configuration**.

**`project_input_actions()` → str**
- Parse the `[input]` section of `project.godot`. Each entry is `action_name={ "deadzone": …, "events": [...] }`. For grounding we surface the **action names** (and optionally a one-line event summary); the agent only needs the names.
- Reuses the `re.search(r"\[input\](.*?)(?:\n\[|\Z)", …)` shape already used for `[autoload]` in `catalogs.py`.

**Input-action lint check (built-in)**
- Mirror `build_catalog_refs()` / the catalog typo-check in `lint.py`, but with a **built-in** `use_pattern` for string-literal args to the input APIs (`Input.is_action_pressed|is_action_just_pressed|is_action_just_released|get_action_strength|InputMap.has_action|action_press|…`) and a `valid_set` = the parsed action names.
- **Only flags near-miss typos** (small edit distance from a real action), never bare unknowns — identical philosophy to the catalog check, so runtime-`InputMap.add_action()` projects don't false-positive. Honors `# lint: ignore`.

**`project_setting(name: str, resolve: bool = False)` → str**
- Default: parse `project.godot` and return the override verbatim. For an absent key, return `"not overridden (engine default applies)"` rather than implying it's unset.
- Covers genuinely useful file-resident settings: `layer_names/2d_physics/layer_1`, `[input]`, `display/window/...`, `physics/...`.
- `resolve=True`: run a tiny generated `extends SceneTree` script via `runner._run` that prints `ProjectSettings.get_setting(name)`, to get the *effective* value including engine defaults. Degrades to the file value with a note if the binary is missing.

**`project_classes()` → str**
- Scan all `.gd` for `class_name X` (optionally capturing `extends Base`), return `X → res://path` (and base). **Source-scan**, reusing `catalogs._gd_signature()` mtime-caching — *not* `.godot/global_script_class_cache.cfg` (the agent is told never to touch `.godot/`).
- Grounds the project's *custom* type vocabulary the way `godot_class` grounds the engine's.

### Phase G — runtime loop

**`godot_screenshot(view: str = "auto")` → image**
- New bridge cmd `screenshot`. Inside the editor process, capture an editor viewport (`EditorInterface.get_editor_viewport_2d()/3d()` chosen by `view` or by the edited-scene root type when `auto`), `get_texture().get_image().save_png()` to a temp path; the Python side reads it and returns **image content** so the agent sees it.
- Honest scope: this shows what the **editor** displays (the edited scene), not live interactive gameplay. Graceful when no scene is open / editor not running.

**`godot_run_game_headless(scene: str = "main", seconds: int = 5, timeout: int = 60)` → str**
- The headless sibling of `godot_run_tests`. `scene` is `"main"` (project main scene) or an explicit `res://` path (no `"current"` — headless has no editor selection).
- Launch via `runner._run` with `--quit-after <frames>` (frames ≈ `seconds × 60`) so Godot **exits 0 cleanly** on a healthy run; the existing subprocess `timeout` is the backstop for a scene that hangs before the frame counter advances.
- Parse the `--log-file` for `SCRIPT ERROR`, `ERROR`, `push_error`, `push_warning`, and stack-trace blocks → structured report (verdict from exit code + parsed errors), shaped like the test summary.

### Phase H — scene authoring (flips the bridge from read-only to mutating)

The bridge gains write cmds. Correctness is borrowed from the engine: mutate in the **open editor** via `EditorInterface` + `EditorUndoRedoManager`, `save_scene`, then **headless reload-check** (instantiate the saved `.tscn` in a subprocess to confirm it loads). On failure: `undo()` + re-save, then report — never leave it broken.

- **`godot_save_scene()`** — expose the cmd already implemented in `bridge.gd` (quick win).
- **`godot_scene_add_node(scene_path, parent_path, type, name)`** — add a node of engine `type` under `parent_path` (NodePath relative to the scene root; `"."` = root), auto-opening `scene_path`.
- **`godot_scene_set_property(scene_path, node_path, property, value)`** — set a property; `value` is a Variant literal parsed in-bridge via `str_to_var()`.
- **`godot_scene_attach_script(scene_path, node_path, script_path)`** — attach an existing `.gd`.
- **`godot_scene_connect_signal(scene_path, from_path, signal, to_path, method)`** — wire a signal between two nodes in the scene.

Each mutation: auto-open target → register the change on `EditorUndoRedoManager` → `save_scene` → headless reload-check → on failure `undo()` + re-save → structured result.

---

## Contracts touched

- **`config.py`** — `resolve_project_path()` + `PathEscapeError` (landed). Phase 0 routes `edit.py` / `scene.py` / `runner.py` through it and removes their private `_abs`/`_res_to_abs` clones.
- **`server.py`** — register the new tools (Phase F: 3; Phase G: 2; Phase H: 5).
- **`addon/godot_grounding_bridge/bridge.gd`** — new cmds: `screenshot` (G); `add_node`, `set_property`, `attach_script`, `connect_signal` (H). `save_scene` already exists. **The addon is installed into each target project by `init`** — existing installs must re-`init` to pick up the new bridge. Needs a **version handshake** (extend `ping` to report a bridge protocol version) so the Python side can tell the user to re-init on mismatch instead of failing with `unknown cmd`.
- **`bridge.py`** — client functions for each new cmd; keep the graceful-degradation pattern.
- **`runner.py`** — `run_game_headless` reuses `_run`; add `--quit-after` handling and a runtime-error log parser (sibling of `_parse_suite`).
- **`catalogs.py` / new module** — `[input]` parser; `project_classes` scanner (reuse `_gd_signature` cache). `project_setting` file parse + optional headless resolve.
- **`lint.py`** — built-in input-action typo rule (new built-in `use_pattern` + `valid_set`); reuses the catalog typo machinery and `# lint: ignore`.
- **Agent grant lists** — `agent/templates/godot-editor.md.tmpl` (`tools:` frontmatter), `godot-editor.toml.tmpl`, and the `SKILL.md.tmpl` reference table must list the new `mcp__godot-grounding__*` tools, or the `godot-editor` agent literally cannot call them. **Easy to forget — it's a hard gate on the feature being usable.**
- **`scripts/smoke_phase4.py`** (per existing convention) — offline where possible, against a TEMP project; never touch capsulecastle. Phase F is fully offline-testable; G/H need a real project + editor and may be smoke-gated behind availability checks like the existing bridge tools.
- **`README.md`** — extend the Tools table and the Live-editor-bridge table.
- **`godot-mcp.toml` profile** — **no new keys** (F surfaces are universal). Worth stating so the planner doesn't add config.

## Edge cases

- **project_setting:** category-prefixed/nested names; `PackedStringArray(...)` and `Vector2(...)` values need readable formatting; `resolve=true` with the binary missing → fall back to file value + note.
- **input actions:** entries span multiple lines (`events` arrays) — the section regex must be non-greedy to the next `[`. Only names are needed for grounding. Built-in (non-overridden) UI actions like `ui_accept` won't appear in `project.godot`; decide whether to seed them so they aren't flagged as typos.
- **project_classes:** duplicate `class_name` (Godot itself errors — surface it); `class_name` only valid at top level (ignore inner classes); cache invalidation rides `_gd_signature`.
- **run_game_headless:** `--headless` uses dummy display/audio — a game that asserts on a real display/audio device may error spuriously (document); main scene not configured; a load-error modal before frame 1 → caught by the timeout backstop; very high/low fps making the seconds→frames estimate loose.
- **screenshot:** no scene open in the editor; `view` mismatch (2D request on a 3D scene); large image size; editor not running (graceful).
- **scene authoring:** editor not open / bridge unreachable (graceful, like existing bridge tools); editor currently *playing* a scene; `node_path`/`parent_path` not found; `str_to_var` parse failure (reject with a clear message); `undo()` when the action wasn't registered; `save_scene` failure; **reload-check false-negative** — scene loads fine but is logically wrong (out of scope; we verify it *loads*, not that it's *correct*); a human editing the same scene concurrently; signal already connected.
- **bridge protocol drift:** new cmd sent to an old installed addon → must produce "re-init the project's addon," not a raw `unknown cmd`.

## Out of scope (this batch)

- **Running-game / live-gameplay screenshots** — needs capture injected into the game process; deferred.
- **`godot_runtime_errors` as a live editor-Output stream** — replaced by the headless run's parsed log.
- **Text-based `.tscn` mutation** — rejected in favor of editor-driven mutation.
- **Node removal / reparenting / deletion** — v1 mutations are add / set / attach / connect only.
- **Resource (`.tres`) authoring or grounding.**
- **Folding `project_classes` into `godot_search` / `godot_class`** (engine+project unified lookup) — later.
- **Type-resolved (vs name-based) analysis** — unchanged; everything stays name-based.

## Open questions

1. **Screenshot framing:** capture just the edited-scene sub-viewport, the active 2D/3D editor viewport, or the whole editor window? (Lean: `get_editor_viewport_2d/3d` by root type, fall back to window grab.)
2. **seconds vs frames:** expose `run_game_headless` duration as `seconds` (≈×60) or as raw `frames` for determinism? (Lean: `seconds`, document the ~60fps assumption.)
3. **Bridge versioning:** put the protocol version in `ping`, or a separate `version` cmd? How loud should the "re-init your addon" nudge be?
4. **`set_property` guardrails:** is `str_to_var` (no eval) sufficient, or do we want a refuse-list for dangerous properties? (Lean: sufficient.)
5. **UI default actions:** seed Godot's built-in `ui_*` actions into the input grounding set so they aren't mistaken for typos, or document that only project-defined actions are grounded?
6. **Phase F lint `use_pattern`:** hardcode the Input/InputMap API surface, or make it profile-extensible like `lint_catalog_ref`?
