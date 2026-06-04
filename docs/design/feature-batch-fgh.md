# Design: Feature Batch F–H — grounding surfaces, runtime loop, scene authoring

Status: reviewed (design audited; all decisions resolved) — ready to plan
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
- **`godot_lint` / `godot_lint_source` read through `edit._abs` too.** `server.py`'s `godot_lint` calls `edit._abs(script_path)` directly (not just through the edit writers), so removing `edit._abs` means this call site must also route through `config.resolve_project_path`. Inventory every `_abs` / `_res_to_abs` *call site* (currently `edit.py` ×3, `scene.py` ×2, `runner.py` ×1, **`server.py:130` ×1**), not just the helper definitions, so no read path is left ungated.
- Note `edit.write_script` already has its *own* inline containment check (`target.resolve().relative_to(...)`) that duplicates the resolver — replace it with `resolve_project_path` so there is exactly one containment implementation.
- **Contain the tools that hand a path straight to Godot, not just through `_abs`:** `runner.check_script` / `run_script` pass the agent's `script_path` to `--script`; validate it through the resolver before launch. (`run_tests` uses a profile-configured scene — already trusted.)
- Net effect: every file-taking tool, read or write, refuses an out-of-root path identically — so the new G/H tools just call the resolver.

**Observable outcome (testability):** a unit/smoke test passes a `..`-escape, an absolute path, and a symlink-escape to each path-taking tool (`godot_lint`, `project_scene`, `godot_lint_scene`, `godot_check`, `godot_run_script`, `godot_write_script`, `godot_patch_script`, `godot_fix_script`) and asserts every one returns the same "Refused" shape rather than reading/launching.

### Phase F — grounding surfaces (cheapest, highest fit, no new infra)

All three are *universal* to every Godot project (parsed from `project.godot` / `.gd` source), so — like the built-in `autoloads` catalog — they need **no profile configuration**.

**`project_input_actions()` → str**
- Parse the `[input]` section of `project.godot`. Each entry is `action_name={ "deadzone": …, "events": [...] }`. For grounding we surface the **action names** (and optionally a one-line event summary); the agent only needs the names.
- Reuses the `re.search(r"\[input\](.*?)(?:\n\[|\Z)", …, re.S)` shape already used for `[autoload]` in `catalogs.py`. (The existing `autoloads()` passes `re.S`; the `[input]` parse needs it too because action entries span multiple lines.)
- **Observable outcome:** against a fixture `project.godot` with two `[input]` actions, returns both names; returns an empty/"none" result (not an error) when the section is absent.

**Input-action lint check (built-in)**
- Mirror `build_catalog_refs()` / `_catalog_findings()` in `lint.py`, but with a **built-in** `use_pattern` for string-literal args to the input APIs (`Input.is_action_pressed|is_action_just_pressed|is_action_just_released|get_action_strength|InputMap.has_action|action_press|…`) and a `valid_set` = the parsed action names.
- **Only flags near-miss typos** (small edit distance from a real action, via the existing `_lev` bounded-Levenshtein and the `_catalog_findings` distance-≤2 logic), never bare unknowns — identical philosophy to the catalog check, so runtime-`InputMap.add_action()` projects don't false-positive. Honors `# lint: ignore`.
- **Wiring:** `lint_source()` currently takes `catalog_refs` from the caller. This built-in rule must be threaded into `lint_source` (and thus into every caller: `godot_lint`, `godot_lint_source`, `edit.write_script`) so it runs on the write path, not only on an explicit lint call. State that wiring explicitly — otherwise the rule exists but never fires on edits.
- **Observable outcome:** `Input.is_action_pressed("jum")` against a project that defines `jump` yields a `warn` suggesting `jump`; `Input.is_action_pressed("totally_new_action")` (no near neighbor) yields nothing.

**`project_setting(name: str, resolve: bool = False)` → str**
- Default: parse `project.godot` and return the override verbatim. For an absent key, return `"not overridden (engine default applies)"` rather than implying it's unset.
- Covers genuinely useful file-resident settings: `layer_names/2d_physics/layer_1`, `[input]`, `display/window/...`, `physics/...`.
- `resolve=True`: run a tiny generated `extends SceneTree` script via `runner._run` that prints `ProjectSettings.get_setting(name)`, to get the *effective* value including engine defaults. Degrades to the file value with a note if the binary is missing (`_run` already returns a "Godot binary not found" `err` on `FileNotFoundError` — detect that and fall back).
- **Observable outcome:** with `resolve=False`, an overridden key returns its file value and an unset key returns the "not overridden" note; with `resolve=True` and a binary present, an unset-in-file key returns the engine default.

**`project_classes()` → str**
- Scan all `.gd` for `class_name X` (optionally capturing `extends Base`), return `X → res://path` (and base). **Source-scan**, reusing `catalogs._gd_signature()` mtime-caching — *not* `.godot/global_script_class_cache.cfg` (the agent is told never to touch `.godot/`).
- Grounds the project's *custom* type vocabulary the way `godot_class` grounds the engine's.
- **Observable outcome:** against a fixture with two `class_name`-bearing scripts, returns both `name → res://` rows; a project with none returns an empty/"none" result, not an error.

### Phase G — runtime loop

**`godot_screenshot(view: str = "auto")` → image**
- New bridge cmd `screenshot`. Inside the editor process, capture an editor viewport (`EditorInterface.get_editor_viewport_2d()/3d()` chosen by `view` or by the edited-scene root type when `auto`), `get_texture().get_image().save_png()` to a temp path; the Python side reads it and returns **image content** so the agent sees it.
- Honest scope: this shows what the **editor** displays (the edited scene), not live interactive gameplay. Graceful when no scene is open / editor not running.
- **Transport note (must resolve before build):** the existing bridge protocol is newline-delimited JSON over TCP and the Python `bridge._send` reads exactly one line. A PNG cannot ride that channel as raw bytes. The bridge must either (a) save the PNG to a temp path and return that *path* in the JSON, with the Python side reading the file (requires the editor and the MCP server to share a filesystem — true for the local-only `127.0.0.1` design), or (b) base64-encode the PNG into the JSON line. State which; "the Python side reads it" currently hides this decision. Lean (a) for parity with the headless `--log-file` approach.
- **Observable outcome:** with a 2D scene open, `godot_screenshot()` returns image content (non-empty PNG); with no scene open, returns a graceful text message, not an exception.

**`godot_run_game_headless(scene: str = "main", seconds: int = 5, timeout: int = 60)` → str**
- The headless sibling of `godot_run_tests`. `scene` is `"main"` (project main scene) or an explicit `res://` path (no `"current"` — headless has no editor selection). An explicit `res://` path is validated through `config.resolve_project_path` (Phase 0).
- Launch via `runner._run` with `--quit-after <frames>` (frames ≈ `seconds × 60`) so Godot **exits 0 cleanly** on a healthy run; the existing subprocess `timeout` is the backstop for a scene that hangs before the frame counter advances.
- Parse the `--log-file` for `SCRIPT ERROR`, `ERROR`, `push_error`, `push_warning`, and stack-trace blocks → structured report (verdict from exit code + parsed errors), shaped like `_parse_suite`'s output.
- **Verdict definition (must be explicit):** define exactly what counts as PASS vs FAIL. Exit-0 alone is not enough — `push_error`/`SCRIPT ERROR` in the log can co-occur with a clean `--quit-after` exit, so the verdict must combine exit code AND a clean parsed log. Specify the combination, mirroring how `run_tests` already blends exit code with parsed counts. [See coherence flag on `--quit-after` exit semantics.]
- **Observable outcome:** a healthy main scene returns PASS with zero parsed errors; a scene that calls `push_error("x")` on `_ready` returns FAIL (or a flagged result) with `"x"` surfaced; a scene that hangs returns the TIMED OUT shape from `_run`.

### Phase H — scene authoring (flips the bridge from read-only to mutating)

The bridge gains write cmds. Correctness is borrowed from the engine: mutate in the **open editor** via `EditorInterface` + `EditorUndoRedoManager`, `save_scene`, then **headless reload-check** (instantiate the saved `.tscn` in a subprocess to confirm it loads). On failure: `undo()` + re-save, then report — never leave it broken.

> **New engine dependency, not a reuse:** `EditorUndoRedoManager` is not used anywhere in the current `bridge.gd` (which only calls `EditorInterface` play/stop/open/save + tree-walk). The rollback story (Decision 8) is brand-new code, so budget for it: the bridge must obtain the manager (`get_undo_redo()` on the `EditorPlugin`), register every mutation as a do/undo action pair, and the reload-check + `undo()` round-trip is the riskiest mechanism in the batch. The "headless reload-check" is a *second* subprocess per mutation (a full Godot launch) — note the latency cost so the planner sizes the smoke gating accordingly.

- **`godot_save_scene()`** — expose the cmd already implemented in `bridge.gd` (quick win).
- **`godot_scene_add_node(scene_path, parent_path, type, name)`** — add a node of engine `type` under `parent_path` (NodePath relative to the scene root; `"."` = root), auto-opening `scene_path`.
- **`godot_scene_set_property(scene_path, node_path, property, value)`** — set a property; `value` is a Variant literal parsed in-bridge via `str_to_var()`.
- **`godot_scene_attach_script(scene_path, node_path, script_path)`** — attach an existing `.gd`.
- **`godot_scene_connect_signal(scene_path, from_path, signal, to_path, method)`** — wire a signal between two nodes in the scene.

Each mutation: auto-open target → register the change on `EditorUndoRedoManager` → `save_scene` → headless reload-check → on failure `undo()` + re-save → structured result.

- **Observable outcome (per cmd):** after `godot_scene_add_node`, a subsequent `project_scene(scene_path)` (or `godot_editor_scene_tree`) shows the new node; a reload-check failure returns a FAIL result AND a follow-up `project_scene` shows the scene unchanged from before the mutation (rollback verified, not just claimed).

---

## Contracts touched

- **`config.py`** — `resolve_project_path()` + `PathEscapeError` (landed). Phase 0 routes `edit.py` / `scene.py` / `runner.py` **and the `server.py:130` `godot_lint` call site** through it and removes their private `_abs`/`_res_to_abs` clones (and `write_script`'s inline duplicate check).
- **`server.py`** — register the new tools (Phase F: 3; Phase G: 2; Phase H: 5).
- **`addon/godot_grounding_bridge/bridge.gd`** — new cmds: `screenshot` (G); `add_node`, `set_property`, `attach_script`, `connect_signal` (H). `save_scene` already exists. **The addon is installed into each target project by `init`** — existing installs must re-`init` to pick up the new bridge. Needs a **version handshake** (extend `ping` to report a bridge protocol version) so the Python side can tell the user to re-init on mismatch instead of failing with `unknown cmd`. **The current `ping` returns `{ok, version}` where `version` is the *Godot engine* version; add a distinct `protocol`/`bridge_version` field rather than overloading `version`, so the Python side and the doctor can both read it without ambiguity.**
- **`bridge.py`** — client functions for each new cmd; keep the graceful-degradation pattern. The screenshot client must handle the chosen image transport (path-vs-base64, above) — `_send` today returns one decoded JSON line only.
- **`runner.py`** — `run_game_headless` reuses `_run`; add `--quit-after` handling and a runtime-error log parser (sibling of `_parse_suite`).
- **`catalogs.py` / new module** — `[input]` parser; `project_classes` scanner (reuse `_gd_signature` cache). `project_setting` file parse + optional headless resolve.
- **`lint.py`** — built-in input-action typo rule (new built-in `use_pattern` + `valid_set`); reuses `_catalog_findings` / `_lev` and `# lint: ignore`. Must be threaded through `lint_source()` so it runs on the write path, not just on explicit `godot_lint` calls.
- **Agent grant lists** — `agent/templates/godot-editor.md.tmpl` (`tools:` frontmatter), `godot-editor.toml.tmpl`, and the `SKILL.md.tmpl` reference table must list the new `mcp__godot-grounding__*` tools, or the `godot-editor` agent literally cannot call them. **Easy to forget — it's a hard gate on the feature being usable.** (Confirmed: the current `.md.tmpl` frontmatter and `SKILL.md.tmpl` tool table enumerate tools explicitly; the `.toml.tmpl` does not list tools in frontmatter but its prose tool-reference should still be updated.)
- **`scripts/smoke_phase4.py`** (next number after the existing `smoke_phase3.py`, per convention) — offline where possible, against a TEMP project; never touch capsulecastle. Phase F is fully offline-testable; G/H need a real project + editor and may be smoke-gated behind availability checks like the existing bridge tools.
- **`README.md`** — extend the Tools table and the Live-editor-bridge table.
- **`godot-mcp.toml` profile** — **no new keys** (F surfaces are universal; the input-lint `use_pattern` is hardcoded — row 15, resolved). Worth stating so the planner doesn't add config.
- **`doctor.py`** — add the bridge-protocol-version check to the health report (so a re-init nudge surfaces from `godot_doctor`, not only at first failing call). Listed because the version handshake is otherwise invisible until a tool fails.

## Edge cases

- **project_setting:** category-prefixed/nested names; `PackedStringArray(...)` and `Vector2(...)` values need readable formatting; `resolve=true` with the binary missing → fall back to file value + note.
- **input actions:** entries span multiple lines (`events` arrays) — the section regex must be non-greedy to the next `[` and use `re.S`. Only names are needed for grounding. Built-in (non-overridden) UI actions like `ui_accept` won't appear in `project.godot` — **hardcode the standard `ui_*` list** into the valid set (row 11, resolved) so they ground and their typos are caught.
- **project_classes:** duplicate `class_name` (Godot itself errors — surface it); `class_name` only valid at top level (ignore inner classes); cache invalidation rides `_gd_signature`.
- **run_game_headless:** `--headless` uses dummy display/audio — a game that asserts on a real display/audio device may error spuriously (document); main scene not configured (return a clear message, not a crash); a load-error modal before frame 1 → caught by the timeout backstop; very high/low fps making the seconds→frames estimate loose.
- **screenshot:** no scene open in the editor; `view` mismatch (2D request on a 3D scene); large image size; editor not running (graceful); the image-transport path/file must be cleaned up like `_run`'s `--log-file` temp file.
- **scene authoring:** editor not open / bridge unreachable (graceful, like existing bridge tools); editor currently *playing* a scene (refuse or stop-first — pick one, don't leave implicit); `node_path`/`parent_path` not found; `str_to_var` parse failure (reject with a clear message); `undo()` when the action wasn't registered; `save_scene` failure; **reload-check false-negative** — scene loads fine but is logically wrong (out of scope; we verify it *loads*, not that it's *correct*); a human editing the same scene concurrently; signal already connected.
- **bridge protocol drift:** new cmd sent to an old installed addon → must produce "re-init the project's addon," not a raw `unknown cmd`.

## Out of scope (this batch)

- **Running-game / live-gameplay screenshots** — needs capture injected into the game process; deferred.
- **`godot_runtime_errors` as a live editor-Output stream** — replaced by the headless run's parsed log.
- **Text-based `.tscn` mutation** — rejected in favor of editor-driven mutation.
- **Node removal / reparenting / deletion** — v1 mutations are add / set / attach / connect only.
- **Resource (`.tres`) authoring or grounding.**
- **Folding `project_classes` into `godot_search` / `godot_class`** (engine+project unified lookup) — later.
- **Type-resolved (vs name-based) analysis** — unchanged; everything stays name-based.

## Resolved during this review (were "open questions")

These were carried as open questions but are **design-level** decisions that downstream items depend on; resolved here so the plan isn't built on a fork. Two genuinely need a human call and are marked.

| # | Question | Resolution |
|---|---|---|
| 10 | seconds vs frames for `run_game_headless` | **`seconds` param, ×60 internally**, document the ~60fps assumption. (Already the signature in Phase G; the leaning was unambiguous and nothing else depends on raw frames.) |
| 11 | Seed Godot's built-in `ui_*` actions into the input grounding set? | **Yes — hardcode the standard `ui_*` list** into the valid set, so they ground and near-miss typos of them are caught. A version-pinned constant; stable across Godot 4.x. |
| 12 | `set_property` guardrails — refuse-list for dangerous properties? | **`str_to_var` (no eval) is sufficient for v1; no refuse-list.** `str_to_var` cannot execute code or call methods, so the eval-injection risk the refuse-list would guard doesn't exist; a refuse-list would be guarding a problem the design does not have. (Revisit only if a future cmd takes expressions.) |
| 13 | Screenshot framing (Open-Q1) | **Resolved by Decision 2 already** — "editor viewport only," `get_editor_viewport_2d/3d` by root type. The "whole editor window" option in the old Open-Q1 *contradicts* locked Decision 2 and is dropped. (See coherence note.) |
| 14 | Bridge versioning — version in `ping` vs separate `version` cmd | **Extend `ping`** with a distinct `bridge_version`/`protocol` field (a separate round-trip is wasteful; `ping` is already the gate every bridge tool calls). Nudge loudness is a wording detail, deferred. |
| 15 | Phase-F lint `use_pattern` — hardcode vs profile-extensible | **Hardcoded built-in `use_pattern`** for the Input/InputMap surface. Keeps the "F surfaces are universal, no config" framing and the "no new profile keys" contract true. Project input-wrapper autoloads are out of scope for the lint (revisit later if needed). |

**Resolved (row 11 — UI default actions):** hardcode the standard Godot `ui_*` action list into the input-grounding valid set, so `ui_accept` et al. ground correctly and near-miss typos of them are caught. The list is a single version-pinned constant in the input module (stable across Godot 4.x) — document it as the one maintained list. (User decision, this review.)

**Resolved (row 15 — lint `use_pattern`):** the Input/InputMap API surface is a **hardcoded built-in** `use_pattern` (like the other built-in lint rules). No new `godot-mcp.toml` key — the "no new profile keys" contract holds. Project-specific input-wrapper APIs (e.g. an `InputManager` autoload) are out of scope for the lint this batch; revisit with a profile key only if a concrete wrapper appears. (User decision, this review.)

## Coherence notes (for the planner — not rule violations)

- **`--quit-after` exit-0 is the linchpin of the Phase-G verdict and is unverified in this repo.** No code in this project currently launches with `--quit-after`, and the entire PASS verdict (Decision 6) rests on the assumption that `--quit-after N` causes Godot to *exit 0 cleanly* after N frames even on a scene that printed `push_error`. If `--quit-after` returns non-zero on its own, or if `push_error` does not affect the exit code, the verdict logic flips. The fix is empirical: validate the exit-code behavior of `--quit-after` against the pinned Godot build before locking the verdict definition, and make the verdict combine exit code AND parsed-log cleanliness rather than exit code alone.
- **Decision 2 vs old Open-Q1 contradicted each other.** Decision 2 locks "editor viewport only"; old Open-Q1 still floated "the whole editor window." Resolved above (row 13) — window-grab dropped to match the locked decision.
- **`godot_save_scene` may be near-useless on its own.** It's listed as a "quick win" exposing an existing cmd, but every H mutation already calls `save_scene` internally, and the editor's own Ctrl+S exists. It's only useful as a standalone tool if the agent ever needs to persist editor state it changed by another path. Keep it (cheap, harmless), but don't count it as a feature — it's plumbing.
- **Per-mutation full Godot subprocess (reload-check) is the cost center.** Each H mutation spawns a fresh headless Godot to instantiate the `.tscn`. At ~1–3s startup each, a multi-node scene built one `add_node` at a time pays that cost per call. Not wrong, but the planner should know the loop is launch-bound and consider whether batch mutations are a fast-follow.
