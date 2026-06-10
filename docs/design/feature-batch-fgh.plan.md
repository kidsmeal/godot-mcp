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

---

# Phase 6.5 — Audit hardening batch (bucket C)

Added 2026-06-10 after the full-tree code audit. Source design: `docs/CODE_AUDIT_2026-06-10.md` (bucket C). Buckets A and B already shipped (`b0bbabd`, Phase 6). Bucket D is parked. This phase is correctness-first hardening sequenced **between Phase 6 and Phase 7** (feature work), per NOW.md.

Conventions read: no `CLAUDE.md`/`CONVENTIONS.md`/`AGENTS.md` at the repo root — matched the surrounding source (every MCP tool is a thin `@mcp.tool()` wrapper in `server.py` delegating to a module fn that graceful-degrades to a string and never raises to the agent; all file paths route through `config.resolve_project_path`).

Verification command: `.venv/Scripts/python.exe -m pytest tests/ -q` (baseline at planning time: **162 passed, 7 skipped**, ruff/mypy clean). The 7 skips are editor/binary-gated. Each phase below ends green on that command plus `ruff check src/godot_mcp tests` and `mypy src/godot_mcp`.

Security invariants every phase preserves (already true in the tree, do not regress): no `shell=True`; path-taking tools resolve through `config.resolve_project_path`; tests never touch the real capsulecastle project — they create a tmp project (`project.godot` only) and `monkeypatch.setattr(config, "PROJECT_ROOT", tmp)` (and `GODOT_MCP_PROFILE` / `GODOT_MCP_DATA` where the unit under test reads them), per the existing `tests/test_containment.py` and `tests/test_profile_robustness.py` fixtures.

## Summary
Six phases covering bucket C: edit-path integrity (C1–C7), validation correctness (C8–C14), the import-time crash class (C15–C16), and grounding-data correctness (C17–C26). Priority items from NOW.md (C1–C5, C8–C10, C15–C21) are load-bearing; lower-priority C items (C6/C7, C11–C14, C22–C31) ride along inside the phase that already touches their file, only where cheap and decision-free. The two H-severity import-time crashers (C15/C16) and the H-severity grounding-data gaps (C17/C18) anchor the ordering.

## Blockers / Open Questions
None of the priority items require a design decision the audit hasn't already made; each names the fix. The items below are genuine decisions the audit leaves open. They are **not** blockers for starting Phase 1 (C5 has a clear directive); they are flagged where they land:

- **C5 verdict vocabulary (Phase 2 decision, not a blocker):** the audit says give `check_script` "a distinguishable UNAVAILABLE verdict and report it separately," but does not fix the surfaced string. The implementer must pick the exact verdict prefix (e.g. `UNAVAILABLE` vs `ENV-ERROR`) and how `write_script` rolls back vs reports on it. Rule: an environment failure (Godot missing / `--check-only` timed out) must NOT say "WRITE ROLLED BACK — script does not parse." Whether the write is kept or rolled back when the checker is unavailable is the open call — recommend: roll back AND label it an environment failure, since an unchecked write violates the parse-guarantee. Confirm with the human before implementing if unsure.
- **C7 concurrency guard (Phase 1, lower-priority, decision-gated):** "a per-path lock plus an mtime check on rollback." A per-path lock is new shared state (see Cross-cutting). If the lock design is non-trivial, ship the mtime check alone in Phase 1 and park the lock — do not invent a locking scheme. Flagged, not blocking.
- **C20 circuit-breaker scope (Phase 5, decision-gated):** "process-wide network-down flag after the first connection failure (distinct from 404)." Whether the flag ever resets within a process lifetime is unspecified. Recommend: latch for the process (a restart clears it), since a doc backfill that went offline once is unlikely to recover mid-session and the cost of re-probing is the 8s stall C20 exists to kill. Confirm if a reset is wanted.

## Phase 1 — Crash class: import-time + config-write safety *(C15, C16)*
**Goal:** one bad `godot-mcp.toml` value or one corrupt `.mcp.json` can never (a) stop the server from booting or (b) destroy other MCP-server registrations.
**Files:** `src/godot_mcp/profile.py` (shape-validate `catalog`/`lint_catalog_ref`/`docs`/`project`/`engine`/`tests` into `Profile.errors` instead of raising — C15); `src/godot_mcp/doctor.py` + `src/godot_mcp/project_ground.py` (isinstance-guard `prof.docs.values()` iteration so a non-dict `docs` can't kill doctor — C15 companion); `src/godot_mcp/init.py` (`_write_mcp_json`: refuse to write + report the parse error on a corrupt/non-dict `.mcp.json`; guard `data["mcpServers"]` non-dict — C16). Extend `tests/test_profile_robustness.py`; new `tests/test_init_mcp_json.py` (covers the zero-coverage `.mcp.json` merge — also closes part of audit D7).
**Verification:** pytest, fully offline:
  - C15: a `godot-mcp.toml` with `[catalog]` (table, not `[[catalog]]` array) → `profile.load` returns a Profile with a populated `errors` list and does NOT raise at import; `doctor.report()` shows a FAIL line and not "All good."
  - C15 companion: a profile with non-dict `docs` → `doctor.report()` and `project_ground` iteration return cleanly (no AttributeError).
  - C16: a `.mcp.json` that is invalid JSON, and one whose top level is a JSON array → `_write_mcp_json` refuses, reports the parse error, and leaves the original file byte-identical (assert other server entries survive).
**Exit criteria:** all new tests green; full suite green; ruff/mypy clean. Import of `godot_mcp.config` against a malformed profile no longer raises (assert via a subprocess or `importlib.reload` under the monkeypatched env).
**Blockers:** none.

## Phase 2 — Validation correctness + env-vs-parse verdict *(C5, C8–C14)*
**Goal:** `godot_validate`/`check_script`/`run_tests` stop producing false-FAILs and stop misattributing environment failures as parse failures (NOW.md stance rule 7 — retry elimination).
**Files:** `src/godot_mcp/runner.py` (UNAVAILABLE verdict from `check_script` + `_run` — C5; restrict `_FAIL_MARKERS` scan to engine-error-shaped lines or post-start-marker — C8; pass `res://`-normalized path to `ResourceLoader.load()` — C9; harness-missing actionable message — C10; `try/finally` around the `--log-file` temp + catch `OSError` — C11; pass `str(abs_path)` to `--script` — C12; close-fd-in-own-try/finally in `run_temp_probe` — C13); `src/godot_mcp/config.py` (refuse the `cmd /c` raw-shim fallback in `resolve_godot` — C14); `src/godot_mcp/edit.py` (C5 consumer side — report UNAVAILABLE distinctly, do not say "does not parse"). New tests: `tests/test_runner_verdicts.py` (extend `tests/test_validate_harness.py` where it fits).
**Verification:** pytest, offline (monkeypatch `runner._run` / `config.resolve_godot` to return canned dicts — no real Godot):
  - C5: stub `_run` to return `{"rc": None, "err": "Godot binary not found ..."}` → `check_script` returns an UNAVAILABLE-class verdict; `write_script` reports an environment failure, NOT "WRITE ROLLED BACK — script does not parse".
  - C8: a log containing an autoload's `"could not find save file"` line plus `VALIDATE_OK` → `_validate_verdict` returns PASS (the benign line no longer false-FAILs).
  - C9: assert the path handed to the harness/loader is `res://...as_posix()` form for a backslash-absolute and a bare-relative input.
  - C10: monkeypatch `config.DATA_DIR` to a dir with no `validate_script.gd` → `validate_with_autoloads` returns "harness missing at <path>", not "No VALIDATE_* marker".
  - C11: stub `subprocess.run` to raise `PermissionError` → `_run` returns the standard err dict and the temp log is gone (assert the file does not exist).
  - C14: a `GODOT_BIN` shim path resolving to the `cmd /c` fallback → `resolve_godot` refuses with "set GODOT_BIN to the .exe".
**Exit criteria:** all new tests green; full suite green; ruff/mypy clean. `_validate_verdict` keeps its existing PASS/FAIL contract for real error logs (regression-asserted).
**Blockers:** C5 verdict-string decision (see Blockers). C8 approach (line-shape filter vs harness start-marker) is the implementer's call — start-marker is more robust but touches `data/validate_script.gd` (Cross-cutting: the harness is a tracked, version-pinned artifact).

## Phase 3 — Edit-path integrity (the rollback promise) *(C1–C4, C6, C7-partial)*
**Goal:** `write_script`/`patch_script`/`auto_fix` never leave the project non-parsing, never mangle CRLF or non-UTF8 bytes, and never silently corrupt strings.
**Files:** `src/godot_mcp/edit.py` (write_script rollback try/except — C1; CRLF detect+preserve — C2; strict UTF-8 decode + clean refusal — C3; string-aware auto_fix — C4; created-dir cleanup on rollback — C6; mtime check on rollback — C7-partial). New tests: `tests/test_edit_integrity.py`.
**Verification:** pytest unit tests against a tmp project, no Godot binary needed (monkeypatch `runner.check_script` to a stub for the rollback/verdict paths):
  - C1: stub `check_script` to raise → assert the original bytes are restored on disk and the function returns a clean message, not a traceback.
  - C2: write a file with CRLF line endings, patch one line → assert the other lines keep CRLF (byte-compare).
  - C3: write a file with invalid UTF-8 bytes, call `auto_fix`/`patch_script` → assert a clean "refused: non-UTF8" message and the bytes on disk are byte-identical (no U+FFFD persisted).
  - C4: a `var x = 5` inside a triple-quoted string is left untouched by `auto_fix`; a real `var x = 5` statement still gets `:=`.
  - C6: a write that rolls back a newly-created file removes the empty parent dirs it created.
**Exit criteria:** all new tests green; full suite still 162+ green; ruff/mypy clean; no behavior change to the happy path (an existing passing write test still passes).
**Blockers:** C7 lock decision (see Blockers) — ship mtime check, park the lock if non-trivial. C5 lives in Phase 2 (it spans `edit.py` + `runner.py` and depends on the new `check_script` verdict, so it is sequenced after the runner verdict change).

## Phase 4 — Grounding data: engine API indexing + search ranking *(C17, C21, C22)*
**Goal:** `godot_search`/`godot_class`/`godot_member` surface the utility functions, global enums, and global constants the dump already contains, and rank member/constant/enum hits so exact matches aren't buried below truncation (NOW.md stance rule 7).
**Files:** `src/godot_mcp/engine_api.py` (index `utility_functions`/`global_enums`/`global_constants` in `_load` and surface them in search/class/member — C17; score member hits exact/prefix/substring + search constants and enums — C21; `get_class` char budget + drill-down tail, builtin `(get None, set None)` cleanup, `_cache` reload-on-redump, JSONDecodeError → "re-run dump_api" message — C22, only where cheap). Extend `tests/test_engine_api.py`.
**Verification:** pytest against a small fixture `extension_api.json` (a trimmed dump checked into `tests/fixtures/` carrying a couple of `utility_functions`, a `global_enums` entry like `Key`, and a class with a member matching a search term) — monkeypatch `config.EXTENSION_API` to it:
  - C17: `search("lerp")` returns the utility function; `godot_class("Key")` resolves (global enum); a global constant is findable.
  - C21: `search("position")` returns `Node2D.position` (or the fixture equivalent) ranked above substring class hits; `search("NOTIFICATION_READY")` and an enum name return matches.
  - C22 (if done): `get_class` on a large fixture class is capped with a "use godot_member" tail.
**Exit criteria:** new tests green; full suite green; ruff/mypy clean. Existing engine_api tests (inherited-member walk, builtin search) still pass.
**Blockers:** none. C22 is opt-in polish — skip any sub-item that isn't a clean mechanical change.

## Phase 5 — Grounding data: docs fetch + cache correctness *(C18, C19, C20)*
**Goal:** doc descriptions stop silently vanishing on `.0` engine builds, the XML cache is version-keyed and crash-safe, and offline doc walks stop costing ~8s per ancestor every restart.
**Files:** `src/godot_mcp/docs.py` (omit patch component when 0 in `_version_tag` — C18; cache under `godot_docs/<tag>/`, temp-write-then-rename, unlink on parse failure — C19; process-wide network-down latch distinct from 404 — C20). New `tests/test_docs.py` (closes part of audit D7 — `docs.py` is currently zero-coverage).
**Verification:** pytest, offline (monkeypatch `urllib.request.urlopen` to a fake; monkeypatch `config.DATA_DIR`/`config.EXTENSION_API` to a tmp fixture):
  - C18: a fake `extension_api.json` header with `version_patch=0` → `_version_tag()` emits `X.Y-stable` (no `.0`); a non-zero patch still emits `X.Y.Z-stable`.
  - C19: cache writes land under `godot_docs/<tag>/<Class>.xml`; a urlopen returning malformed XML leaves no file behind (assert no partial cache file); a second call for a different tag does not read the first tag's cache.
  - C20: a fake urlopen raising a connection error (not HTTP 404) sets the network-down flag; a subsequent `class_docs` call for a different class does NOT attempt a network fetch (assert urlopen called once). A 404 does NOT trip the latch.
**Exit criteria:** new tests green; full suite green; ruff/mypy clean.
**Blockers:** C20 reset-scope decision (see Blockers) — recommend latch-for-process.

## Phase 6 — Doctor drift + remaining grounding parsers *(C17-doctor, C23–C31 where cheap)*
**Goal:** doctor reports artifact drift (binary-vs-dump version, missing harness) per NOW.md stance rule 8, and the remaining lower-priority parser/correctness items ride along where they're decision-free.
**Files:** `src/godot_mcp/doctor.py` (check `data/validate_script.gd` exists; compare dump header against `resolve_godot() --version`; fix the substring version match so API `4.1` no longer passes against feature `4.10` — C17 doctor additions); `src/godot_mcp/project_ground.py` + `src/godot_mcp/catalogs.py` (fingerprint over (relpath, mtime) pairs not (count, mtime_sum); hoist the duplicated `_gd_signature` to one shared helper — C23); `src/godot_mcp/scene.py` (quote-state tracking in the `.tscn` sectioner — C24, **only if a focused test can prove the phantom-node fix**); plus the cheap lows (C25 BOM via `utf-8-sig`, C26 multiline-string state in `refs.py`, C27 trailing-comment lint scan, C28 `--test-filter` docstring caveat, C30 doctor stale-config reload note, C31 `copytree` addon install + uninstall removes the bridge addon) **each only where it is a clean, decision-free change**. Add focused tests per item touched.
**Verification:** pytest, offline:
  - C17-doctor: monkeypatch `config.DATA_DIR` with no harness → doctor shows a FAIL for the missing harness; a dump header `4.1` against project features `4.10` → version-match line is FAIL (not a false OK).
  - C23: rename a project `class_name` file (preserving count and mtime-sum) → `project_classes()` returns the new path, not the stale one.
  - C24 (if done): a `.tscn` with a multiline string value whose content starts with `[node ...]` → the sectioner does not emit a phantom node.
  - Any other C25–C31 item done gets one focused assertion.
**Exit criteria:** new tests green; full suite green; ruff/mypy clean. Doctor still reports "All good." on a healthy tmp project.
**Blockers:** C24 quote-state tracking is the only non-trivial parser change here — if it can't be made decision-free and test-provable in one focused pass, park it to a follow-up and ship the doctor + C23 + cheap-lows portion. C29 (async tool wrapping) is explicitly out of scope for 6.5 (it touches the FastMCP event-loop model and is a behavior decision, not a hardening fix) — leave only the docstring caveat (C28 family).

## Cross-cutting concerns
- **Import-time crash surface (C15)** — `config.py:20` calls `profile.load(PROJECT_ROOT)` at module import, so any exception in `profile.load` kills every tool and doctor before it can run. C15 must convert all shape violations into `Profile.errors` (never raise). This touches the single load-bearing import path shared by every module; verify with an import-under-malformed-profile test, not just a `load()` unit test. Lands Phase 1. No migration; rollback is reverting the phase commit.
- **`.mcp.json` is shared multi-server state (C16)** — the file holds every MCP server the user has registered, not just `godot-grounding`. The current silent `data = {}` fallback destroys all of them on a parse error. The fix must be non-destructive (refuse + report, leave the file untouched). This is user-data integrity, not internal state. Lands Phase 1. Rollback: revert; no data migration needed since the fix only adds a refusal path.
- **`data/validate_script.gd` is a tracked, version-pinned artifact** — C8 (start-marker approach) and C10 (harness-missing message) both touch the harness contract. If C8 adds a start marker the harness must print, the marker string is a contract between `data/validate_script.gd` and `runner._validate_verdict`; change both in the same commit. The harness runs by absolute path from `config.DATA_DIR` and is shared by `godot_validate` and (later) Phases 7/8 — do not change its output format without updating every parser. Lands Phase 2.
- **`extension_api.json` schema assumptions (C17)** — indexing three new top-level buckets (`utility_functions`, `global_enums`, `global_constants`) assumes their shape in the dump. Pin the fixture used in tests to the real 4.6.2 dump shape; if a future re-dump changes the schema, the doctor binary-vs-dump check (also C17) is the drift alarm. No migration; the dump is regenerated by `scripts/dump_api.ps1`, out of scope here. Lands Phases 4 (indexing) + 6 (doctor drift check).
- **Docs cache layout change (C19)** — moving from `godot_docs/<Class>.xml` to `godot_docs/<tag>/<Class>.xml` orphans the existing flat cache. This is a disposable derived cache (re-fetched on demand), so no migration is required, but note it: after this ships, the old flat files under `data/godot_docs/` are dead and can be deleted in the same commit or left to rot harmlessly. Confirm `data/godot_docs/` is gitignored/untracked derived data (not committed) before relying on that. Lands Phase 5.
- **`_gd_signature` duplication (C23)** — the helper is currently copy-pasted in `project_ground.py` and `catalogs.py` with separately-maintained skip-dir sets. Hoisting to one shared helper changes both call sites; the fingerprint change (count,mtime_sum → (relpath,mtime) pairs) changes the cache-invalidation contract, so a stale cache from before the change should be treated as a miss (re-scan), not trusted. Lands Phase 6.
- **Verdict vocabulary (C5)** — adding an UNAVAILABLE verdict class changes the strings `write_script`/`check_script`/`godot_validate` return to the agent. Agent-facing string changes are low-risk here (no external users per NOW.md stance) but the new verdict must be distinguishable from both OK and the parse-FAIL string so the agent doesn't retry-loop. Lands Phase 2.
- **No new MCP tools, no grant-list ripple** — bucket C is pure hardening; it adds no `@mcp.tool()`. The agent grant lists (`godot-editor.md.tmpl`, `godot-editor.toml.tmpl`, `SKILL.md.tmpl`) and the README tool table do NOT change in 6.5. The exact-roster `ci_smoke.py` assertion stays green unchanged. (Naming/rename work is Phase 6.6, a separate thread.)
