# Code audit (2026-06-10)

Five parallel review passes over the full tree, committed plus the uncommitted Phase 5 diff:
server/config/profile layer, bridge, validate/edit/lint path, grounding/data layer,
install/CI/tests/templates. Findings marked **reproduced** were triggered empirically, not
eyeballed. Items already planned in `docs/design/feature-batch-fgh.plan.md` Phases 6-8 are
excluded unless the audit changes their scope.

Buckets:

- **A** — fold into the uncommitted Phase 5 diff before phase-review/commit
- **B** — scope additions for Phase 6 (bridge hardening, already queued)
- **C** — new hardening phase between Phases 6 and 7
- **D** — portability + CI batch (parked; moves up if external users become a goal)

Severity: H = wrong data / broken core guarantee / crash, M = real but bounded, L = polish.

---

## A. Phase 5 diff (fix before review/commit)

All on surfaces the Phase 5 diff just touched.

- **A1 (H)** `project_ground.py:19-79` — the hardcoded `ui_*` roster is wrong for the pinned
  4.6.2 engine: `ui_graph_snap` does not exist in `InputMap::get_builtins()`, and 14 real
  actions are missing (`ui_text_completion_query`, `ui_text_caret_add_below`,
  `ui_text_caret_add_above`, `ui_graph_duplicate`, `ui_graph_follow_left`,
  `ui_graph_follow_right`, `ui_close_dialog`, `ui_accessibility_drag_and_drop`,
  `ui_focus_mode`, `ui_unicode_start`, `ui_filedialog_delete`, `ui_filedialog_find`,
  `ui_filedialog_focus_path`, `ui_colorpicker_delete_preset`). Verified against the
  `4.6.2-stable` tag of `core/input/input_map.cpp`; re-verify against the pinned build when
  fixing. Base names only (`.macos` entries are platform variants of the same action).
- **A2 (H)** `lint.py:248` — `re.findall(ref["valid_pattern"], source)` is unguarded; an
  invalid `valid_pattern` in the profile raises through `lint_source` and crashes every
  lint and write tool. Reproduced. The Phase 5 `re.error` guard at line 243 covers
  `use_pattern` only. Same family: `lint.py:253` — a `use_pattern` that compiles but has no
  capture group raises `IndexError` (`m.group(1)`). Reproduced. Guard both: `try/except
  re.error` on the valid side, skip refs where `use_rx.groups < 1`.
- **A3 (M)** `lint.py:274-301` — the input-action typo lint flags registration sites:
  `InputMap.add_action("jump2")` warns as a typo of `jump`. Reproduced. The catalog check
  has a same-source exemption (`valid_pattern` matches in the linted source); the input rule
  needs the equivalent (pre-scan for `InputMap.add_action("...")` and union into the valid
  set).
- **A4 (M)** `lint.py:274-277` — `_INPUT_ACTION_RX` misses common shapes: single-quoted
  action strings, `event.is_action_pressed(...)` / `event.is_action(...)` (only `Input.` /
  `InputMap.` receivers match — the standard `_input(event)` pattern never fires), and args
  2-4 of `get_axis` / `get_vector` (only the first string arg is captured).
- **A5 (M)** `project_ground.py:259-269` — `setting(name, resolve=True)` interpolates `name`
  unescaped into the generated probe GDScript; a name containing `"` breaks out of the
  string literal and executes arbitrary GDScript in the headless probe. Validate `name`
  against `^[A-Za-z0-9_/.\-]+$` before building the probe.
- **A6 (L)** `tests/test_phase5.py:325-338` — `test_resolve_true_uses_run_temp_probe`
  asserts through the wrong branch: the fake probe output lacks the `__SETTING_VALUE__`
  marker, so the test passes via the "probe output unclear" fallback and the marker-parsing
  path is untested. Have the fake return `__SETTING_VALUE__MyGameName` and assert on the
  resolved-value message.

## B. Phase 6 scope additions (bridge)

Phase 6 as queued covers per-client buffers/framing, a `bridge_version` field in `ping`, and
a doctor check. The audit adds:

- **B1 (H)** `bridge.gd:27` (listen) + dispatch at 61-93 — no authentication on the command
  channel. Any local process can connect and drive the editor: `run` executes the project,
  `open_scene` loads arbitrary scenes whose `@tool` scripts execute in-editor, `save_scene`
  writes to disk. Loopback is not user-scoped on Windows. Fix: per-session random token
  generated at `_enter_tree`, written to a user-only-readable file both sides share,
  required on every command. Also defeats a port-squatter impersonating the bridge.
- **B2 (M)** `bridge.gd:85-86` — `save_scene` is dispatchable on the wire ahead of Phase 8,
  with none of Phase 8's safeguards, and is the only cmd returning `{"ok": false}` with no
  `error` key. Remove the branch until Phase 8 lands.
- **B3 (M)** `bridge.py:32-37` — `TimeoutError` and every `OSError` collapse into "bridge
  not reachable — open the editor", misdiagnosing a connected-but-stalled command as
  not-running; an empty response surfaces as a raw `Expecting value` JSON error. Catch
  `ConnectionRefusedError` alone for the not-running message; report timeout/reset/empty as
  distinct errors.
- **B4 (L)** `bridge.py:44,49,54,59,64,69` — every wrapper does `r["error"]`, which
  KeyErrors on a response lacking the key (see B2). Use
  `r.get("error", "bridge returned a malformed response")`.
- **B5 (M)** `bridge.gd:70-75` + `server.py:274-277` — `run` with any unrecognized `scene`
  value silently falls through to `play_main_scene()` and reports success. Validate
  `scene in {"main", "current"}` on both sides.
- **B6 (M)** `bridge.gd:79-84` — `open_scene` has no server-side path validation; the
  containment check lives only in the Python wrapper, so a direct TCP client passes any
  absolute/UNC/`..` path into `open_scene_from_path`. Refuse non-`res://` and `..` paths in
  the addon. Also: `server.py:294-300` reports "Opened X" for a path that does not exist —
  add an `.exists()` check before sending.
- **B7 (M)** `bridge.gd:53` — framing refinement for the planned F-8 work: accumulate raw
  bytes via `get_partial_data` and split on `\n` in bytes; the current per-chunk
  `get_utf8_string(avail)` corrupts multi-byte UTF-8 straddling a packet boundary. Cap the
  per-client buffer (unauthenticated memory growth otherwise).
- **B8 (L)** `bridge.gd:57-58` — blocking `put_data` on the editor main thread; a client
  that stops reading can stall the editor UI once the TCP window fills. Queue outbound bytes
  and flush with `put_partial_data` from `_process`.
- **B9 (L)** `bridge.gd:44-49` — unlimited clients, no idle timeout; half-open peers are
  polled every editor frame forever. Cap concurrent clients (one suffices for the
  connect-per-command Python client) and drop idle connections.
- **B10 (L)** `bridge.py:24-31` — the read loop's timeout is per-`recv` and the buffer is
  unbounded; a peer dripping bytes keeps the tool call alive indefinitely. Track an absolute
  deadline and cap `buf` (~1 MiB).

## C. Hardening phase (edit-path integrity, crash class, grounding data)

### C-1. Edit-path integrity (the rollback promise)

- **C1 (H)** `edit.py:46-55` — no exception handling around write → parse-check → rollback:
  if `check_script` raises (reproduced via subprocess `PermissionError`), the broken content
  stays on disk and the backup is lost. Direct violation of "never leave the project
  non-parsing". Wrap in try/except that restores the backup on any exception.
- **C2 (M)** `edit.py:69` → `:44` — `patch_script` reads with universal newlines and writes
  `newline="\n"`, converting every CRLF in the file to LF; a one-line patch rewrites the
  whole file. Reproduced. Detect the dominant newline at read time and preserve it.
- **C3 (M)** `edit.py:88,121` — `auto_fix` reads with `errors="replace"` and writes the
  result back, persisting U+FFFD mojibake into untouched bytes. Reproduced. Strict-decode
  first and refuse non-UTF8 files. Same family: `edit.py:69` — `patch_script` raises a raw
  `UnicodeDecodeError` on non-UTF8 input instead of a clean refusal. Reproduced.
- **C4 (M)** `edit.py:94-116` — `auto_fix` regexes are not string-aware: `var x = 5` inside
  a triple-quoted string gets rewritten to `:=`; the result parses, so the corruption
  persists silently. Track multiline-string state before applying mechanical fixes.
- **C5 (M)** `edit.py:55` + `runner.py:163-178` — when Godot is missing or `--check-only`
  times out, `write_script` reports "WRITE ROLLED BACK — script does not parse",
  misattributing an environment failure as a parse failure. Give `check_script` a
  distinguishable UNAVAILABLE verdict and report it separately.
- **C6 (L)** `edit.py:43,50-54` — rolling back a created file unlinks it but leaves the
  freshly `mkdir(parents=True)`-created directories. Record created dirs, remove empty ones
  on rollback. Evidence the silent mkdir path fires on bad input: an empty
  `CUsersatk67Documentsgodot-mcptests` dir (backslash-stripped path) sat in the repo root,
  created Jun 3; deleted during this audit. Root cause is D3 (unvalidated `GODOT_PROJECT`).
- **C7 (L)** `edit.py:41-49` — rollback is a blind backup-restore with no mtime check; a
  concurrent external write (the Godot editor saving) can be clobbered by a stale backup. A
  per-path lock plus an mtime check on rollback is the only concurrency guard worth adding.

### C-2. Validation correctness

- **C8 (M)** `runner.py:186-229` — `_FAIL_MARKERS` ("could not find", "not declared",
  "could not load", case-insensitive) scan the whole boot log, so any autoload that prints
  e.g. "could not find save file" at startup makes every `godot_validate` false-FAIL
  forever. Restrict the scan to engine-error-shaped lines, or have the harness print a start
  marker and scan only after it.
- **C9 (M)** `runner.py:252` — `validate_with_autoloads` validates the resolved path but
  passes the raw caller string to `ResourceLoader.load()`; bare-relative and
  backslash-absolute forms are not valid loader paths and FAIL spuriously (verified
  pass-through). Pass `"res://" + abs_path.relative_to(root).as_posix()`.
- **C10 (M)** `runner.py:251-252` — the harness path `DATA_DIR / "validate_script.gd"` is
  never checked; if missing, the verdict blames the user's script ("No VALIDATE_* marker").
  Return an actionable "harness missing at <path>" message. Companion: doctor never checks
  the harness exists (see C17).
- **C11 (M)** `runner.py:41-62` — `_run` has no try/finally for the `--log-file` temp file;
  any subprocess exception other than `TimeoutExpired`/`FileNotFoundError` (reproduced with
  `PermissionError`) leaks the log and raises raw. Move cleanup into `finally`, catch
  `OSError` into the standard err dict.
- **C12 (L)** `runner.py:151,168` — `check_script`/`run_script` resolve the path for
  containment but pass the original string to `--script` (symlink-swap TOCTOU). Pass
  `str(abs_path)`.
- **C13 (L)** `runner.py:279-281` — in `run_temp_probe`, if `os.write` fails the fd is never
  closed and the Windows unlink in `finally` then fails on the open handle. Close the fd in
  its own try/finally.
- **C14 (L)** `config.py:87-92` — the `["cmd", "/c", shim]` fallback lets `&`/`^` in a path
  act as command separators under cmd.exe re-parsing. Refuse the raw-shim fallback with a
  "set GODOT_BIN to the .exe" message.

### C-3. Crash class (one bad config kills the server)

- **C15 (H)** `profile.py:57` (via `config.py:20` import-time load) — a wrong-shaped TOML
  value (`[catalog]` table instead of `[[catalog]]` array) hits `.keys()` on a string,
  AttributeError at import, the server never boots and doctor can never run. Reproduced.
  Shape-validate `catalog` / `lint_catalog_ref` / `docs` / `project` / `engine` / `tests`
  and push violations into `Profile.errors`. Companion: `doctor.py:67` +
  `project_ground.py:107` iterate `prof.docs.values()` without an isinstance guard, so a
  non-dict `docs` kills doctor itself (reproduced).
- **C16 (H)** `init.py:94-100` — a corrupt or non-dict `.mcp.json` is silently replaced with
  `{}`, destroying every other MCP server registration in the file. Refuse to write and
  report the parse error instead; also guard `data["mcpServers"]` being a non-dict.

### C-4. Grounding data (the core promise)

- **C17 (H)** `engine_api.py:18-37` — `_load()` never indexes `utility_functions` (114:
  lerp, clamp, randi...), `global_enums` (22: Key, MouseButton, Error...), or
  `global_constants`. `godot_search("lerp")` misses the real lerp; `godot_class("Key")` is
  "not found". Verified live against the real dump. Index the three top-level buckets and
  surface them in search/class/member. Doctor additions ride along: check
  `data/validate_script.gd` exists; compare the dump header against `resolve_godot()
  --version` (binary-upgraded-dump-stale passes cleanly today, `doctor.py:37-48`); fix the
  substring version match (`doctor.py:44` — API `4.1` passes against feature `4.10`).
- **C18 (H)** `docs.py:29-37` — `_version_tag()` always emits `X.Y.Z-stable`, but Godot tags
  .0 releases as `X.Y-stable` (verified: 404 vs 200), so on any .0 engine every doc fetch
  404s and descriptions silently vanish. Omit the patch component when 0.
- **C19 (M)** `docs.py:20,82-84,93,109-113` — the XML cache is not version-keyed (stale docs
  served forever after an engine upgrade) and writes are non-atomic with no cleanup on parse
  failure (a partial file re-poisons every restart). Cache under `godot_docs/<tag>/`, write
  temp-then-rename, unlink on parse failure.
- **C20 (M)** `docs.py:81-96` — doc fetches run synchronously per tool call with
  `timeout=8` and no offline circuit-breaker; offline, an `include_inherited` class walk
  blocks ~8s per ancestor, every restart. Set a process-wide network-down flag after the
  first connection failure (distinct from 404).
- **C21 (M)** `engine_api.py:311-335,348-354` — member search hits are unranked and always
  sort after all class hits; `search("position")` buries the exact `Node2D.position` behind
  the truncation. Verified live. Score member hits exact/prefix/substring like classes.
  Same area: constants/enums are never searched (`engine_api.py:303-319`) —
  `search("NOTIFICATION_READY")` and `search("ProcessMode")` return no matches.
- **C22 (L)** `engine_api.py` polish: no output cap on `get_class` (~40KB for Control with
  inheritance — add a char budget + "use godot_member" tail, lines 115-218); builtin members
  print `(get None, set None)` (230-235); `_cache` pins a `_missing` state and never reloads
  on re-dump (15-24); a corrupt dump raises raw `JSONDecodeError` instead of a "re-run
  dump_api" message (25).
- **C23 (M)** `project_ground.py:298-310` + `catalogs.py:70-83` — the mtime-cache
  fingerprint `(count, mtime_sum)` is blind to renames (rename preserves both), so
  `project_classes()` serves stale `res://` paths after a move. Fingerprint over
  (relative path, mtime) pairs. Also: `_gd_signature` is duplicated across both modules with
  separately maintained skip-dir sets — hoist one shared helper.
- **C24 (M)** `scene.py:29-41` — the line-based `.tscn` sectioner has no quote-state
  tracking; multiline string values (shader `code`, multiline `text`) misparse — a string
  line starting with `[node ...]` creates a phantom node that steals subsequent properties
  (reproduced), and `lint_scene` can false-error on string content. Track unterminated-quote
  state across lines. Polish nearby: `_unq` never unescapes `\"`/`\\` (21-22);
  `instance_placeholder` nodes render as kind `?` (86-88).
- **C25 (L)** project.godot parsing edges: BOM breaks `^`-anchored matches on line 1
  (`config.py:53-57`, use `utf-8-sig`); `override.cfg` is never consulted so file-mode
  `setting()` / input actions can be silently wrong (`project_ground.py:180-188,242-255` —
  parse it or document the limitation); quoted keys (`"my action"={`) never match the
  bare-identifier regexes (`project_ground.py:188,371`, `catalogs.py:22`); a multi-line
  setting value reports as a bare `{` (`project_ground.py:244-250`).
- **C26 (L)** `refs.py:17-35` — `_mask` is per-line, so triple-quoted multi-line string
  contents classify as live code refs, and the escape check mis-handles `\\"`. Carry
  multiline-string state and count consecutive backslashes.
- **C27 (L)** lint polish: typo lints scan trailing comments (`lint.py:249-250,287-288` —
  commented-out code false-positives, reproduced); `is_test` checks `/tests/` with forward
  slashes only (`lint.py:205`).
- **C28 (L)** `server.py:225-229` — `godot_run_tests` docstring promises `--test-filter`
  for all frameworks but only the custom runner understands it; with gut/gdunit4 the agent
  believes a filtered subset ran. Add a docstring caveat or per-framework mapping.
- **C29 (L)** `server.py` (all tools) — FastMCP runs sync tools inline on the event loop
  (verified), so a 300s `godot_run_tests` blocks every other call. Make the
  subprocess-launching tools async via a thread, or document.
- **C30 (L)** `doctor.py` / `config.py:20` / `runner.py:23-24` — profile and test-scene
  config load once at import; after editing `godot-mcp.toml`, doctor re-reports stale state
  with no restart hint. Doctor should re-load fresh and note the diff.
- **C31 (L)** `init.py:182-184` — addon install copies top-level files only (a future
  subdirectory drops silently; `read_text` would corrupt a future binary asset) — use
  `copytree`. `init.py:104-136` — uninstall leaves `addons/godot_grounding_bridge/` (the
  TCP-listening plugin) in the project; remove it and note the `editor_plugins` entry.

## D. Portability + CI batch (parked)

The README advertises public one-liner installs; today they only work on this machine.

- **D1 (H)** `setup.ps1:42` — fresh-machine install crashes under stock Windows PowerShell
  5.1 (where `iwr|iex` lands): the `2>$null` import probe under `$ErrorActionPreference =
  "Stop"` promotes python's expected stderr to a terminating error before pip install runs.
  Reproduced. Probe via exit code without redirecting stderr under Stop.
- **D2 (H)** `install.sh:35-52` + `init.py:150-156` — the located Godot is never persisted
  on macOS/Linux: init writes `GODOT_BIN: "godot"` into `.mcp.json` (which then overrides
  the user's env), and install.sh has no PATH-shim equivalent of `setup.ps1:74-86`. Every
  runner tool fails after a "successful" unix install. Thread the resolved binary into init
  and write it into the profile/.mcp.json, or symlink `~/.local/bin/godot`.
- **D3 (M)** `config.py:16-17` — `DEFAULT_PROJECT` hardcodes
  `C:\Users\atk67\Documents\capsulecastle` (also in `.mcp.json.example:7` and
  `agent/INSTALL.md:11-12`); on any other machine an unset `GODOT_PROJECT` silently grounds
  every tool against a nonexistent dir. A relative/mangled `GODOT_PROJECT` is also accepted
  silently and `write_script`'s mkdir then creates literal trees in cwd (see C6 evidence).
  Require an absolute path containing `project.godot` before any tool writes; surface the
  unset state from doctor first. Related: installer env var is `GODOT_MCP_PROJECT`, runtime
  reads `GODOT_PROJECT` — honor the alias or have doctor warn on the mismatch.
- **D4 (M)** installer parity: `install.sh:15-21` has no git-less fallback (install.ps1
  does); `install.sh:37-41` probes only `command -v godot` on Linux (no `godot4`, flatpak,
  snap); `install.ps1:27` for git-less users deletes the whole install dir on every re-run
  (nuking venv + dumped API) before re-extracting.
- **D5 (L)** `setup.ps1` polish: the PATH shim is only written when absent so a Godot
  upgrade leaves it stale even with `-Force` (line 78); the PATH-presence check is a
  substring match (line 83, `*$bin*` false-positives); `TrimEnd` throws under EAP=Stop when
  the User Path value is absent (line 84).
- **D6 (M)** `.github/workflows/ci.yml:10` — single ubuntu-latest job (Python 3.12) for a
  Windows-primary tool; all path/containment/glob code is CI-tested only on Linux, and the
  symlink-containment tests skip on this dev box (no Developer Mode), so that guarantee is
  effectively untested on the primary platform. Add a windows-latest leg running the offline
  pytest suite. Also: CI installs pytest/ruff/mypy unpinned (`ci.yml:35`) — install the
  pyproject `dev` extra or pin.
- **D7 (M)** zero-test modules: `docs.py`, `refs.py`, `init.py` (especially the `.mcp.json`
  merge logic, given C16). Partial gaps: `scene.py` has containment tests only (no parse
  tests), `runner.py` `run_tests`/`check_script` offline-untested, `catalogs.py` happy path,
  `doctor.py` non-profile checks.
- **D8 (L)** packaging drift: runtime deps duplicated between `pyproject.toml` and
  `requirements.txt` with no `[build-system]` table (metadata is decorative);
  `scripts/client_check.py:10` hardcodes `.venv\Scripts\python.exe` (the only end-to-end
  stdio test is Windows-only and absent from CI); `scripts/smoke_profile.py:7,53` hardcodes
  `C:\Users\atk67\...`; `scripts/smoke.py:23-27` prints stale `capsule_*` tool names.
- **D9 (L)** agent-template instruction drift (grants are all present, see below):
  `godot-editor.md.tmpl` "Ground before you act" lacks the four Phase 5 grounding bullets
  that `godot-editor.toml.tmpl:10-13` has, and its Confirm stage omits `godot_validate`;
  `SKILL.md.tmpl` Stage 0 doesn't mention the four new tools (table rows only) and the tool
  table omits `godot_editor_ping` / `godot_editor_scene_tree`.

## Verified clean

- README tool table matches the actual 30-tool `server.py` roster exactly; `ci_smoke.py`'s
  expected roster too.
- All 4 Phase 5 tools are present in the agent template grant lists (`.md.tmpl` frontmatter,
  SKILL table).
- Both bridge ends bind strictly loopback; no wildcard exposure.
- No `shell=True` anywhere; list-args subprocess throughout (C14's cmd-shim fallback is the
  one exception).
- `write_script`'s rollback restore is byte-exact (`read_bytes`/`write_bytes`); final
  newlines preserved by `auto_fix` and `patch_script`.
- gdtoolkit AST lint rules held under adversarial probing (return-type detection, typed
  args, lambda exclusion); `_lev` bound/early-exit correct; catalog same-source exemption
  works.
- `[input]` section regex survives real multi-line event blocks; comment-led lines can't
  match the key/class_name scanners; `find_files` containment/truncation sound.
- `run_temp_probe` cleanup solid on success and in-`_run`-exception paths; no zombie
  processes on timeout; CI genuinely downloads Godot 4.6.2 and enforces smoke + pytest +
  ruff + mypy.
