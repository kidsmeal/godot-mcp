# Probe-Leak Hardening — Investigation & Replan Notes

Status: **investigation complete, implementation NOT started** (paused for replanning).
Date: 2026-06-03.
Scope: stop the godot-grounding MCP plugin from leaking temp probe / validation
scripts into the tracked game-project root (`C:\Users\atk67\Documents\capsulecastle`).

---

## 1. The reported leak

Three uncommitted files were found in the capsulecastle **project root** and hand-deleted:

| File | What it was | Risk |
|---|---|---|
| `__validate_tmp.gd` | A `SceneTree` harness that loads a target script path and prints a VALIDATE marker. The plugin's runtime **autoload-aware parse probe**. | Leaks into a tracked repo on a crash mid-validation. |
| `__broken_syntax.gd` | A deliberately **uncompilable** fixture to confirm the linter catches syntax errors. | **Intentionally uncompilable — would break a full-project headless parse if ever staged.** |
| `__broken_after_autoload.gd` | A deliberate **missing-symbol** fixture to confirm the linter catches undeclared-identifier errors. | Same class of repo pollution. |

At pause time: **no stray `__*.gd` remain** in the capsulecastle root (verified).

---

## 2. Where the plugin actually lives (grounding for the replan)

- MCP server: `C:\Users\atk67\Documents\godot-mcp` (wired via `capsulecastle/.mcp.json`
  → `godot-grounding`, `GODOT_PROJECT=...\capsulecastle`).
- Server entry: `src/godot_mcp/server.py` (thin `@mcp.tool()` wrappers).
- Headless launcher: `src/godot_mcp/runner.py` — `_run(extra_args, timeout)` runs
  `godot --headless --path PROJECT_ROOT --log-file <OS-temp> <extra_args>`. Already uses
  `tempfile.mkstemp` + `_safe_unlink` for the **log file** (the pattern to copy for probes).
- Containment helper (already exists): `config.resolve_project_path(path)` raises
  `PathEscapeError` on `..`/absolute/symlink escapes.
- Plugin data dir: `config.DATA_DIR` (= `<repo>/data`).
- The harness payload already exists as **`data/validate_script.gd`** — currently
  **untracked** (`git status` shows `?? data/validate_script.gd`) and **not referenced by
  any Python code**. It is the source the leaked `__validate_tmp.gd` was copied from.
- The skill (`capsulecastle/.claude/skills/godot/SKILL.md`) and agent templates
  (`agent/templates/*.tmpl`) do **not** themselves write probes.

### Key finding
The committed plugin has **no Python codepath that writes `__validate_tmp.gd` or the
`__broken_*.gd` files**. The validate harness is unwired. The leak therefore came from a
**manual / interactive workaround**: to run a `SceneTree` autoload-validator (or to exercise
the linter on broken input), the existing tools (`godot_run_script`, `godot_check`,
`godot_lint`) all require an **in-project `res://` path** — so the harness and fixtures were
copied into the project root to be runnable, and leaked.

---

## 3. Root cause

`godot_run_script` / `godot_check` / `godot_lint` only accept paths that resolve **inside**
`PROJECT_ROOT` (via `_res_to_abs` / `_abs`). There is **no sanctioned way to run a
plugin-owned harness against the project**, so the harness gets copied in. Likewise there is
no in-plugin home for deliberately-broken linter fixtures, so they get dropped in the project.

## 4. Experiment run (de-risks the fix)

Verified empirically against `Godot_v4.6.2-stable_win64.exe`:

> A `SceneTree` harness placed in the **OS temp dir** (absolute path) and launched as
> `godot --headless --path <capsulecastle> --script <ABS temp path> -- res://systems/save_system.gd`
> **runs successfully, the project loads, autoloads register**
> (`ProjectSettings.has_setting("autoload/SaveSystem") == true`), and the harness
> `ResourceLoader.load`s the in-project target.

**Conclusion:** the validator harness does **not** need to live inside the project at all.
It can run from the plugin's own `data/` dir (or OS temp) by absolute `--script` path while
`--path` still registers the project's 13 autoloads. Zero project-root writes required.

---

## 5. The three requested fixes (unchanged ask)

1. **Runtime probes** → unique OS-temp path (or gitignored `.godot/` subdir), **not** the
   project root, deleted in a `finally`/`defer` so a crash can't leak them.
2. **Deliberate broken fixtures** (`__broken_*.gd`) → the plugin's own **test directory**,
   not the game project root.
3. **`.gitignore` backstop** in capsulecastle (e.g. `__*.gd`, `__*.gd.uid`) as
   defense-in-depth.

---

## 6. Proposed implementation (DRAFT — to be replanned, nothing applied yet)

### A. Runner hardening (`src/godot_mcp/runner.py`)
- **Static harness, no runtime write (recommended over "write to temp each call").** Keep
  `data/validate_script.gd` as a tracked plugin asset and run it by **absolute path** from
  `config.DATA_DIR`. Because it's identical every call and lives outside the project, it has
  **zero leak surface** — strictly better than re-writing it to OS temp per call.
  - New `validate_with_autoloads(script_path, timeout=60)`:
    contain via `resolve_project_path`; launch `_run(["--script", str(DATA_DIR/"validate_script.gd"), "--", res_path], timeout)`;
    decide pass/fail by scanning the engine log for Parse/Compile/SCRIPT errors (the harness
    header says exit code is unreliable — `ResourceLoader.load` returns non-null on compile fail).
- **Generated probes → OS temp + `finally`.** For genuinely per-call generated probes
  (e.g. the planned `project_setting(resolve=True)` `print(ProjectSettings.get_setting(...))`
  script), add `run_temp_probe(source, user_args, timeout)` that `mkstemp(suffix=".gd",
  prefix="godot_mcp_probe_")`, runs by absolute path, and `_safe_unlink`s the file **and its
  `.gd.uid`** in a `finally` — mirroring the existing `--log-file` handling.

### B. Wire a sanctioned tool (removes the root cause)
- Add `godot_validate(script_path, timeout=60)` in `server.py` delegating to
  `runner.validate_with_autoloads`. Without a sanctioned tool, agents keep hand-copying the
  harness into the project and the leak recurs.
- **Grant + doc ripple (do not forget):**
  - `agent/templates/godot-editor.md.tmpl` `tools:` frontmatter — add
    `mcp__godot-grounding__godot_validate` (else the `godot-editor` subagent can't call it).
  - `agent/templates/SKILL.md.tmpl` tool-reference table + the capsulecastle live skill
    `.claude/skills/godot/SKILL.md` (Stage 2 + tool table).
  - `README.md` Tools table.
  - Existing scaffolded projects must re-`init` to pick up the grant.
- **Track `data/validate_script.gd`** (currently untracked) so the harness ships with the plugin.

### C. Fixtures → plugin test dir (`tests/fixtures/`)
- Create `tests/fixtures/broken_syntax.gd` (uncompilable) and
  `tests/fixtures/broken_after_autoload.gd` (undeclared-identifier), with a short README
  noting they are **deliberate negative fixtures** and must never be staged into a game project.
- Safe in the plugin repo (a Python project — no full-project headless parse there).
- Note: the plugin has **no `tests/` dir or pytest yet** (the F–H plan's *Bootstrap* phase
  is what stands up pytest). Decide whether fixtures land now as standalone files or wait for
  Bootstrap — see open questions.

### D. `.gitignore` backstops
- capsulecastle `.gitignore`: add `__*.gd` and `__*.gd.uid`. (Note: `.uid` is already
  globally ignored there, so `__*.gd.uid` is redundant-but-explicit.)
- Optionally plugin `.gitignore`: add `__*.gd` / `__*.gd.uid` for symmetry (harness lives in
  `data/`, so unaffected).

---

## 7. Open questions for the replan

1. **Scope creep vs root-cause fix.** The literal ask is fixes 1–3 (where probes are
   written + fixtures + gitignore). Wiring a new `godot_validate` MCP tool (§B) is the *real*
   fix but is a feature addition with grant/README/skill ripple. **Confirm: wire the tool now,
   or just land the safe runner helpers + fixtures + gitignore and defer the tool?**
2. **Relationship to the F–H batch.** `docs/design/feature-batch-fgh.{md,plan.md}` is an
   in-flight reviewed plan (Bootstrap → 0 → F → G → H) that introduces pytest, the path
   resolver adoption, and other probe-style runs (`project_setting resolve`,
   `run_game_headless`). The probe-temp pattern (§A `run_temp_probe`) and the fixtures/pytest
   (§C) **overlap that plan**. Decide: fold this hardening into the F–H plan (e.g. a Phase 0.5
   / Bootstrap addendum) or ship it as a standalone pre-fix first?
3. **Harness home: `data/` (tracked, recommended) vs OS-temp-per-call** — the user's fix #1
   wording implies write-to-temp; the experiment shows static-in-`data/` is cleaner. Confirm
   the preferred shape.
4. **Validator verdict semantics.** Lock exactly which log markers count as failure
   (`Parse Error`, `SCRIPT ERROR`, `Compile Error`, `... not declared`, `Could not find/load`)
   and confirm against the pinned build, since exit code is unreliable for this harness.
5. **Fixtures timing** — land `tests/fixtures/` now, or with the Bootstrap pytest phase?

---

## 8. What was NOT changed (clean slate for replanning)
- No edits to any plugin source, templates, README, or skill.
- No fixtures created; no `.gitignore` edits.
- `data/validate_script.gd` left as-is (untracked).
- Only this notes file was written.
