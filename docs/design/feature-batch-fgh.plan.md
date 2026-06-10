# Plan (revised): correctness/containment hardening + Feature Batch F–H

Status: **active plan — revised 2026-06-03 after a live-probe review.**
Supersedes the first planner draft, which assumed Phase 0 containment was "mostly done." A manual probe proved otherwise (outside-project `godot_lint` / `godot_check` / `godot_run_script` / `godot_lint_scene` all succeeded), and surfaced engine-grounding and profile bugs the F–H design never covered. **Correctness and containment move ahead of features; Phase H is gated behind its safety prerequisites.**

Design references: `docs/design/feature-batch-fgh.md` (F/G/H feature design, reviewed) and `docs/design/probe-leak-hardening.md` (probe/validation leak investigation — folded in here as Phase 1B). This plan adds a hardening/correctness track in front of the features.

Conventions: no `CLAUDE.md`/`CONVENTIONS.md` exist; match the surrounding source. Every MCP tool is a thin `@mcp.tool()` wrapper in `server.py` delegating to a module fn that graceful-degrades (returns a string, never raises to the agent); path handling routes through `config`.

---

## Findings register (from the live-probe review)

| ID | Pri | Finding | Evidence | Fix lands in |
|---|---|---|---|---|
| F-1 | **P0** | Containment broken across **read/run** tools: `godot_lint` reads via `edit._abs`; `project_scene`/`godot_lint_scene` via `scene._abs`; `godot_check`/`godot_run_script` hand caller input straight to Godot. Confirmed live on an absolute outside-project path. | server.py:130, scene.py:59, runner.py:159 | Phase 1 |
| F-2 | **P1** | Edit path **leaks outside-project content before refusing**: `patch_script` reads the target before the protected writer; `auto_fix` reads before any check. No write, but reveals existence/content. | edit.py:63, edit.py:82 | Phase 1 |
| F-3 | P2 | Bridge **path-taking tools bypass the resolver**: `godot_open_scene` forwards raw input into `EditorInterface.open_scene_from_path`. | server.py:226 → bridge.py:67 → bridge.gd:79 | Phase 1 |
| F-4 | **P1** | Engine grounding **false negatives for inherited members**: `godot_member("Sprite2D","add_child")` → "No member" (valid via Node). Lookup scans only the exact class. | engine_api.py:155 | Phase 2 |
| F-5 | **P1** | `godot_search` **ignores built-in classes** (and singletons): `godot_search("from_hsv")` finds nothing though `Color.from_hsv` exists. Loops only `idx["classes"]`. | engine_api.py:207 | Phase 2 |
| F-6 | **P1** | **Broken profiles silently degrade to defaults**: a malformed `godot-mcp.toml` is swallowed to `{}`, and `doctor` still reports a normal profile (`add(True, …)`) + "All good." Catalogs/tests/docs vanish invisibly. | profile.py:50, doctor.py:58 | Phase 3 |
| F-7 | P2 | **Profile catalog validation brittle**: `_specs`/`_parse`/`build_catalog_refs` assume `name/file/pattern/use_pattern/valid_pattern` exist; a bad profile crashes a tool instead of producing a doctor error. | catalogs.py:25, catalogs.py:100 | Phase 3 |
| F-8 | P2 | **Bridge protocol too naive for larger payloads**: addon parses each available TCP chunk as whole JSON; TCP has no message boundaries, so `set_property`/`screenshot` will eventually split. Needs per-client buffers + framing. | bridge.gd:51 | Phase 6 |
| F-9 | P2 | **Verification too weak for a safety tool**: no `tests/`; CI runs only `ci_smoke.py`, whose tool-count assertion (`len(names) >= 15`) is loose and missed every containment bug. | ci_smoke.py:32 | Phases 1 & 4 |
| F-10 | P3 | **Worktree hygiene**: `.claude/settings.local.json` untracked w/ broad perms and not git-ignored; gantry-init placeholder docs still contain `<DATE>`/`<path>`. | repo root | Housekeeping |
| F-11 | **P1** | **Plugin leaked temp probe/validation scripts into the TRACKED game-project root** (`__validate_tmp.gd`, `__broken_*.gd` — one intentionally uncompilable). Root cause: no sanctioned way to run a plugin-owned `SceneTree` validator or hold broken-linter fixtures, so they get hand-copied into the project. `data/validate_script.gd` is the legitimate harness source (untracked). | `docs/design/probe-leak-hardening.md` | Phase 1B |

---

## Revised phase order

Each phase: tests-first where the harness exists, ends green (`pytest`; + `ruff`/`mypy` from Phase 4 on), stops for human commit. Never advance without a committed prior phase.

### Phase 1 — Containment, for real + regression tests  *(F-1, F-2, F-3, partial F-9)*
The urgent one — the fix the whole batch waits on.
- Delete the private `_abs` / `_res_to_abs` helpers in `edit.py`, `scene.py`, `runner.py`; route **every** file-taking path through `config.resolve_project_path`, **refusing before any read or Godot launch**. Replace `write_script`'s inline duplicate check too.
- Cover the confirmed sites: `godot_lint` (server.py:130), `project_scene`/`godot_lint_scene` (scene.py:59), `godot_check`/`godot_run_script` (runner.py:159), **`patch_script` read-before-refuse** (edit.py:63), **`auto_fix`** (edit.py:82), and **`godot_open_scene`** res:// validation before the bridge send.
- Stand up **minimal pytest** (`tests/`, `[tool.pytest.ini_options]` `pythonpath=["src"]`) — just enough to write the regression suite. (ruff/mypy formalization is Phase 4.)
- **Containment regression tests** for ALL of: `godot_lint`, `project_scene`, `godot_lint_scene`, `godot_check`, `godot_run_script`, `godot_write_script`, `godot_patch_script`, `godot_fix_script`, `godot_open_scene` — each fed `..`-escape / absolute / symlink-escape, asserting the identical "Refused" shape with no read/launch. **Red before the fix, green after.**
- **Exit:** one containment implementation; every path-taking tool refuses escapes identically; the probe cases that were RED are now GREEN-covered.

### Phase 1B — Probe/validation harness hardening  *(F-11)* — root-cause fix for the probe leak
Full investigation: `docs/design/probe-leak-hardening.md`. The plugin has no sanctioned way to run a plugin-owned `SceneTree` validator against the project, so the harness + broken-linter fixtures got hand-copied into the tracked capsulecastle root and leaked. Experiment confirmed: a harness in the plugin's own `data/` launched by **absolute** `--script` path with `--path <project>` loads the project and registers autoloads with **zero project-root writes**.
- **Track the harness:** `git add data/validate_script.gd` (currently untracked). It runs by absolute path from `config.DATA_DIR` — identical every call, outside the project, zero leak surface. *(Supersedes the earlier "stray file — delete" note in housekeeping.)*
- **`runner.validate_with_autoloads(script_path, timeout=60)`** — contain `script_path` via `resolve_project_path`, launch `data/validate_script.gd` by abs path with the target as `--` arg, decide pass/fail by scanning the engine log (exit code is unreliable for this harness — lock the failure markers: `Parse Error`, `SCRIPT ERROR`, `Compile Error`, `not declared`, `Could not find/load`, against the pinned build).
- **`runner.run_temp_probe(source, user_args, timeout)`** — for genuinely per-call generated probes, `mkstemp(suffix=".gd", prefix="godot_mcp_probe_")`, run by abs path, `_safe_unlink` the file **and its `.gd.uid`** in a `finally` (mirrors the existing `--log-file` cleanup). **Prerequisite reused by Phase 5 (`project_setting(resolve=True)`) and Phase 7 — build it once here.**
- **Sanctioned tool `godot_validate(script_path, timeout=60)`** in `server.py` → `validate_with_autoloads`, so agents never copy a harness into a project again (the actual root-cause fix). Grant ripple: 3 templates + README (cross-cutting).
- **Fixtures → `tests/fixtures/`** in the plugin repo (safe there — no full-project headless parse): `broken_syntax.gd` (uncompilable) + `broken_after_autoload.gd` (undeclared identifier), with a README marking them deliberate negatives. Rides the minimal pytest from Phase 1.
- **`.gitignore` backstop:** add `__*.gd` to the plugin `.gitignore`. The same backstop in the *capsulecastle* repo is a separate cross-repo change (note it — can't be committed from this repo).
- **Exit:** `godot_validate` validates an in-project script via the plugin-owned harness; `run_temp_probe` leaves nothing behind on success OR crash (finally-cleanup tested); fixtures live in the plugin; no `__*.gd` can reach the game root.

### Phase 2 — Engine grounding correctness  *(F-4, F-5)*
- `godot_member`: resolve **inherited** members by walking the `inherits` chain (`idx["ci"]` → record → `inherits` → …), scanning each ancestor; label which class a member is inherited from.
- `godot_class(name, include_inherited=False)`: optional flattened view including inherited members.
- `godot_search`: include `idx["builtins"]` **and** singletons, not just `idx["classes"]`.
- **Tests:** `Sprite2D.add_child` resolves (inherited from Node); `godot_search("from_hsv")` finds `Color.from_hsv`; `Vector2.snapped` searchable.
- **Exit:** inherited + built-in lookups correct; tests green.

### Phase 3 — Profile robustness  *(F-6, F-7)*
- `profile.load`: distinguish "no file" from "present but unparseable / schema-invalid." Record an explicit error state (don't silently fall to `{}`).
- `catalogs`: validate each spec has its required keys; a bad spec → clean doctor error, **not** a tool crash.
- `doctor.report`: surface profile parse/schema errors as a **FAIL** — a malformed toml can never coexist with "All good."
- **Tests:** malformed `godot-mcp.toml` → doctor FAIL; catalog spec missing `pattern` → doctor error, tools don't raise.
- **Exit:** broken profiles are loud, not silent; tests green.

### Phase 4 — Toolchain formalization + CI  *(F-9)*
Now that real coverage exists, formalize around it.
- Add `[tool.ruff]` + `[tool.mypy]` (pragmatic: target `src/godot_mcp`, `ignore_missing_imports`, not `--strict`) + a `dev` optional-deps group; green baseline.
- Wire `pytest` + `ruff check` + `mypy` into CI **alongside** the untouched Godot-gated `ci_smoke.py`.
- Strengthen `ci_smoke.py`'s loose `len(names) >= 15` into an **exact expected-tool-set** assertion so a dropped/renamed tool fails CI.
- **Exit:** `pytest`/`ruff`/`mypy` green locally + CI; ci_smoke asserts the real roster.

### Phase 5 — Feature F: grounding surfaces
- `project_input_actions()` — parse `[input]` (`re.S`); **hardcode the standard `ui_*` set**; built-in **typo-lint** rule (hardcoded `use_pattern`, threaded through `lint_source` so it fires on the write path).
- **Carried from Phase 3 review:** harden `lint.py:242` — wrap `re.compile(ref["use_pattern"])` in `try/except re.error`. It's the last catalog-ref path that can still raise `re.error` to the agent (a `lint_catalog_ref` whose `use_pattern` value is invalid regex); fits here since Phase 5 already touches `lint.py`.
- `project_setting(name, resolve=False)` — file parse + optional headless resolve.
- `project_classes()` — `class_name → res://` scan, `_gd_signature` cached.
- **`project_layers()`** — named 2D/3D physics + render layers from `project.godot` (same parse family; flagged high-value in review).
- Grant lists (×3) + README updated for every new tool.
- **Exit:** each tool correct on fixtures; lint fires on the write path; no new profile keys.

### Phase 6 — Bridge hardening  *(F-8 + audit bucket B)* — prerequisite for G/H

Original scope (F-8) + all bucket-B audit findings added here before implementation.

#### Framing + protocol (original F-8)
- **B7/Per-client receive buffers + newline-framed byte reassembly** in `bridge.gd`: accumulate raw bytes via `get_partial_data`, split on `\n` in bytes (not per-chunk UTF-8 decode — that corrupts multi-byte chars at packet boundaries). Cap per-client buffer at 1 MiB to prevent unauthenticated memory growth.
- Distinct **`protocol`/`bridge_version`** field in `ping` response (not overloading the engine `version` key) + a **`doctor` bridge-version check** that reports the bridge protocol version or "bridge not reachable".

#### Security (B1 — highest priority)
- **B1** Per-session random auth token: generated at `_enter_tree` in `bridge.gd`, written to a temp file (user-readable only). Python `bridge.py` reads it from the same path and sends it as a `"token"` field on every command. The addon checks the token before dispatching; missing/wrong token → `{"ok": false, "error": "unauthorized"}`. Defeats any local process impersonating the bridge.

#### Protocol correctness (B2, B5, B6)
- **B2** Remove the `save_scene` branch from `bridge.gd` entirely — it's live ahead of Phase 8 with none of its safeguards, and returns `{"ok": false}` with no `"error"` key. Remove until Phase 8.
- **B5** Validate `scene` value in `run` cmd: `{"main", "current"}` only on both sides (bridge.gd + bridge.py). Any unrecognized value currently falls through silently to `play_main_scene()`.
- **B6** Add server-side path validation in `bridge.gd` for `open_scene`: refuse any path that doesn't start with `res://` or contains `..`. (Python-side containment check already exists.) Also: `bridge.py:open_scene` should call `config.resolve_project_path` before sending (`.exists()` check so "Opened X" is never reported for a missing path).

#### Error handling (B3, B4, B8, B9, B10)
- **B3** `bridge.py._send`: catch `ConnectionRefusedError` alone for the "not running" message; `TimeoutError` → "bridge timed out"; `ConnectionResetError`/empty-response → distinct "bridge disconnected" message. `json.JSONDecodeError` on empty response → friendly error (not a raw exception).
- **B4** All `bridge.py` wrappers use `r["error"]` which KeyErrors on a well-formed `{"ok": false}` with no `error` key. Replace all with `r.get("error", "bridge returned a malformed response")`.
- **B8** `bridge.gd._send`: replace blocking `put_data` with an outbound byte queue flushed via `put_partial_data` in `_process`. A client that stops reading can currently stall the editor UI.
- **B9** `bridge.gd`: cap concurrent clients at 1 (one connect-per-command Python client is the design), drop/refuse a second connection. Add an idle timeout (~30 s) to drop half-open peers instead of polling them forever.
- **B10** `bridge.py._send`: track an absolute deadline (`time.monotonic() + timeout`) across the recv loop; cap `buf` at 1 MiB. Currently: per-`recv` timeout, unbounded buffer.

#### Exit criteria
- A command whose serialized JSON payload exceeds one TCP MTU (~1460 B) round-trips intact.
- `ping` response includes a `"bridge_version"` field (e.g. `"1.0"`); `doctor` reports it or "bridge not reachable (no version check)".
- Auth token is checked; an unauthorized client gets `{"ok": false, "error": "unauthorized"}`.
- `save_scene` is gone from the wire until Phase 8.
- `run` with `scene="unknown"` returns an error on both sides.
- `open_scene` with a `..`-escape or absolute path is refused by the addon (not just Python).
- Error messages from `bridge.py` are human-readable for the three failure modes (not-running, timeout, disconnected).
- Tests: offline (monkeypatching socket/`_send`) covering B2, B3, B4, B5, B6-Python side, B10. GDScript-side tests (B1, B6-GD, B7, B8, B9) are editor-gated — skip/xfail without the bridge running.

### Phase 7 — Feature G: runtime loop
- `godot_run_game_headless` — **first task: empirically verify `--quit-after` exit-code behavior**; verdict = exit code AND clean parsed log.
- `godot_screenshot` — editor viewport, temp-file-path transport (safe over the buffered protocol).
- **`godot_validate_scene_load(scene_path)`** — headless "does this `.tscn` instantiate?" check; standalone value **and reused as Phase 8's reload-check**.
- Binary-gated tests (skip/xfail without Godot).
- **Exit:** verdict locked only after the `--quit-after` check; screenshot returns image + degrades gracefully.

### Phase 8 — Feature H: scene authoring  *(gated)*
**Do not start until Phases 1, 6, and `godot_validate_scene_load` (Phase 7) are committed** — without containment, tests, bridge versioning/framing, and a real reload-check, scene mutation is "a loaded nail gun."
- First decision (design left implicit): editor **currently playing a scene → refuse vs stop-first** — pick one.
- 5 cmds (`save_scene` exposure + `add_node`/`set_property`/`attach_script`/`connect_signal`) via `EditorInterface` + `EditorUndoRedoManager`, save, reload-check, rollback via `undo()` + re-save.
- Editor-gated tests; **provable rollback** test (failed reload-check ⇒ `project_scene` shows the scene unchanged).
- **Exit:** all five persist on success and **provably roll back** on failure.

---

## Backlog (post-batch, not yet planned)
- **`godot_lookup`** — one unified lookup across engine classes, **inherited** APIs, project `class_name`s, autoloads, and input actions. Natural successor once Phases 2 + 5 land (it composes their fixes).
- **`godot_format_script`** — full `gdformat` pass through the parse-checked/rollback writer.
- Batch scene mutations (amortize the per-mutation Godot launch cost flagged in review).

## Housekeeping  *(F-10 — fold into Phase 1's commit or a quick chore)*
- `.gitignore`: add `.claude/` (the untracked `settings.local.json` carries broad local perms) and `__*.gd` (probe backstop, F-11).
- `docs/CURRENTNESS_AUDIT.md` + `docs/RUNTIME_VERIFICATION_QUEUE.md`: fill `<DATE>`/`<path>` placeholders or remove until first real use.
- **`data/validate_script.gd`: do NOT delete — it's the legitimate validator harness (F-11); it gets *tracked* and wired in Phase 1B.**

## Cross-cutting concerns (carried across phases)
- **Agent grant lists** — every new tool must be added to `godot-editor.md.tmpl` frontmatter, `godot-editor.toml.tmpl` prose, and the `SKILL.md.tmpl` table, or the subagent can't call it.
- **README** — Tools + Live-editor-bridge tables per new tool.
- **TEMP-project isolation** — all tests set `GODOT_PROJECT` to a temp dir before importing `config`; never touch capsulecastle.
- **Verdict baseline** — Green today: `ci_smoke.py`, `client_check.py`, `smoke_phase2.py`, `smoke_phase3.py`. Red by probe (the Phase-1 target): outside-project `godot_lint`/`godot_check`/`godot_run_script`/`godot_lint_scene`/`patch_script`/`auto_fix`.
