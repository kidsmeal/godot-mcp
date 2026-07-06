# NOW (read me first)

<!-- claudhd: opt-in marker (do not remove) - ClauDHD's hooks only act on a NOW.md that has this line -->

One active thread at a time. This file is the cursor: what is live, the next physical action, and what is queued behind it. Read it first, update it as you go.

_Committed, so it follows your branch: `git checkout` swaps this cursor to that branch's thread._

Last touched: 2026-07-03

## Active thread (only one)

**Procgen tool suite — headless tileset build + biome island generation (`procgen_*`)**

Design: `docs/design/procgen-tools.md` (v2 — water-bottom law + in-house matcher decided). Plan: `docs/design/procgen-tools.plan.md` (6 phases; **0–3 self-contained in this repo, 4–6 gated on the game repo `C:\Users\atk67\Documents\squareds\project1` providing dump hooks**). Same gated loop per phase: implementer (native, sonnet/opus) → phase-reviewer (**codex `gpt-5.5`, standing** — `.gantry/models.json`) → fix/re-review → commit + push. Engine IS reachable here: Godot 4.6.2 at `C:\Users\atk67\Desktop\Godot_v4.6.2-stable_win64.exe` (pass as `GODOT_BIN`, overrides the profile), capsulecastle profile at `C:\Users\atk67\Documents\capsulecastle` (`GODOT_PROJECT`).

**Predecessor DONE:** Feature Batch F–H (Phases 1–6.6) COMPLETE + pushed — `main == origin/main`; full ship detail in SHIPPED.md.

Next physical action:

- [x] Procgen naming DECIDED 2026-07-03 — family `procgen_*` (rationale in `procgen-tools.md` §2 + stance rule 4; `worldgen_*` rejected as too narrow). `6b4e313` (pushed).
- [x] Procgen P0 — recon + headless harness (throwaway `procgen_ping`): composes GDScript → `runner.run_temp_probe` → parse JSON between `PROCGEN_JSON_BEGIN/END` sentinels; pattern documented for the 6 real tools to copy. Live-verified vs Godot 4.6.2 on capsulecastle (`Godot 4.6.2-stable (official) — procgen harness OK`). `660e76a`. Reviewer PASS-WITH-NOTES. 308 passed / 7 skipped.
- [x] Procgen P1 — `procgen_tileset_build`: declarative `.tres` TileSet builder; `blob47`/`blob16` peering-bit tables from first principles (256→47 via corner-implies-both-sides), animation-aware scan, load-bearing op-order, per-run nonce sentinel (hardened, shared harness), `procgen_ping` retired. Live-verified vs 4.6.2 (synthetic fixture + real ForgottenPlains one-off, 567 tiles). `d904466`. Opus-fallback PASS initially; later **codex-reviewed → 4 real findings fixed** in hardening pass `e8ccfa5` (JSON config support, tile-level animation validation, separation grid math, animation-field ConfigError) + 2 docstrings.
- [x] Procgen P2 — `procgen_terrain_audit`: signature-coverage audit; expected set derived from the terrain-set mode (reused blob tables, not hardcoded); returns a markdown table + the machine `coverage` dict (fenced json) the game-repo matcher consumes. Both P1 carry-ins landed (frame_offset guard collapsed, conditional physics/nav layers). `66e2d67`. **codex-reviewed → 2 real findings fixed** (dropped coverage dict, wrongly-scoped law check); #4 editor-agent finding resolved by decision (procgen stays off the editor subagent, dedicated `godot-procgen` agent deferred until suite complete — plan amended `230d0d5`).
- [x] **codex reviewer RESOLVED 2026-07-03** — deleted the `service_tier="priority"` line from `~/.codex/config.toml` (user-approved); direct + gantry-pipeline smokes green. codex is the live standing reviewer (`.gantry/models.json`) and has caught real defects on P1 (4) and P2 (2) the gates + opus fallback missed. Current suite state: 383 passed / 7 skipped, all pushed, `main == origin/main` at `e8ccfa5`.
- [x] Procgen P3 — S1 matcher spike (GATE) **PASSED**. Synthetic full-coverage MATCH_CORNERS tileset; matcher resolved a toy landmass (bay + interior pond): all 5 hand-computed picks correct, 0 misses, 96×96 resolve in **17.9ms** (~12% of the 150ms budget). Port-ready corner-signature helper (diagonal-corner Wang rule) + `## S1 verdict` recorded in `procgen-tools.md`; offline spec-lock test `tests/test_terrain_matcher_spec.py`. `087c06a`. Reviewed codex PASS-WITH-NOTES. **Unblocked the game plan's phase 3 (`systems/worldgen/terrain_matcher.gd` is a port of the recorded helper).**
- [x] blob16_corners bug (surfaced by the S1 spike) FIXED — MATCH_CORNERS emitted axis-aligned corner bits (`TOP_CORNER`) where a square grid needs diagonal (`TOP_RIGHT_CORNER`); `strategy="blob16_corners"` built 0/16, now 16/16. `01677a6`. Reviewed codex PASS. Live-verified.
- [x] **MILESTONE: procgen plan phases 0–3 COMPLETE + codex-clean + pushed** (T1 `procgen_tileset_build`, T2 `procgen_terrain_audit`, S1 gate). `main == origin/main` at `01677a6`; **393 passed / 7 skipped**, ruff + mypy clean.
- [x] **Post-0–3 real-art track (chosen option a): `minifantasy_edges` strategy SHIPPED** `9ff8783`. Parameterized 3×5 corner-Wang edge block; cell→signature order mapped empirically off real plains, confirmed identical on desert; placed per-sheet by config `origin`; MATCH_CORNERS, covers 15/16 (the all-corners interior is the 1 missing). Reviewed codex PASS. Real plains + desert built one-off, coastlines render correct (orchestrator eyeballed both). 399 passed / 7 skipped.
- [x] **Design conversation grounded (water + biomes, 2026-07-04):** islands-only world; 4-biome roster (plains/desert/ice/swamp) on unified `#4070d0` blue water (swamp fixed on import, uses 2 of its 4 frames); Plants&Foliage = decor-only; water color hand-authored per biome on import (no normalizer/modulate tooling — a **custom cell-selector UI is unnecessary**: per-sheet variation is just `origin`/frame params, and Godot's TileSet terrain editor already is the visual selector for off-layout sheets). All recorded in `procgen-tools.md` §1.
- [ ] **IN PROGRESS — `interior` param for `minifantasy_edges`** (opus implementer running): interior ground cells get the all-4-corners signature (the 16th class), MULTIPLE = variants the matcher scatters for a varied interior → clean 16/16, waffle gone. Then build real **plains** (grass edges @ (25,3) + grass interior variants) and real **desert** (SAND ground + the **sand-water** edge block below the green, ~rows 17–21 — user-corrected) to 16/16 + re-render. Committed part = synthetic 16/16 test; real builds = evidence for user eyeball. Next after commit: a **full biome tileset** = edge block + interior variants + the 2-frame water animation via `[[animation]]` (frame handling is the remaining scaffolding).
- [ ] **PARKED (game-gated):** plan phases 4–6 (`procgen_worldgen_preview`/`island_preview`/`chunk_lint`/`gen_smoke`) need the game repo `squareds/project1` dump hooks (game plan phases 2–3). Also parkable mcp-side: `procgen_atlas_grid` inspector helper (the grid-overlay used to read sheets).

Rule: when you finish a step, check it off and write the next single tiny step. Do not start another thread until this one ships or you consciously move it to the Queue.

## Queue (in order, not now)

What is eligible to become active next, in order. Items clear triage's readiness gate before they land here: each is either a ready task (carries a one-line "done" + first action) or a spike (the unknown to resolve before it can be built). Nothing queues as a bare one-liner.

> Pruned 2026-07-03: Phases 6 / 6.5 / 6.6 shipped (SHIPPED.md); the **procgen suite was promoted out of this queue to the active thread** (top of file) once 6.6 shipped and its `procgen_*` naming was settled — P0 is done, P1 is next.

1. **Phase 7 — Feature G: runtime loop**. Done = `godot_run_game_headless` (+ empirical `--quit-after` exit-code check) + `godot_screenshot` (editor viewport) + `godot_validate_scene_load`. Carry: add a bare `ERROR:`/runtime marker to the verdict once probes execute code.
2. **Phase 8 — Feature H: scene authoring** (gated on Phases 1, 6, and `validate_scene_load`). Done = 5 bridge mutation cmds + undo + reload-check + a provable-rollback test. Carry into the design before build: **UID-sidecar rule** — any tool that creates/moves/renames a `.gd`/`.gdshader` must create/move the `.uid` sidecar with it (capsulecastle is fully UID-migrated, 735 sidecars; a missed sidecar silently re-IDs the file and rots `uid://` refs in scenes).
3. **Portability + CI batch** (audit bucket D; parked — moves up if external users become a goal). Done = `setup.ps1` works on stock PS 5.1 (D1), unix installs persist the located Godot (D2), no hardcoded capsulecastle default (D3), windows CI leg + pinned dev deps (D6), tests for the zero-coverage modules (D7). First action: spike D1/D2 on a clean VM or fresh user account.
4. **Feature batch I — grounding completion** (from the 2026-06-10 feature review; all offline, no new infra, same shape/size as Feature F). Done = (a) `res://` path-existence lint on the write path + standalone check (294 load/preload sites in capsulecastle; binary exact check, not near-miss), (b) `project_groups()` + near-miss typo-lint mirroring the input-action pattern (85 call sites, 9 group names, no registry exists anywhere — a typo'd group returns an empty array silently), (c) `project_script_api(path)` — methods/signals-with-arity/exports parsed per script, the project-side sibling of `godot_class` (grounds 690 signal use sites + the 13 autoload APIs), (d) `project_resource(path)` — read-only `.tres` summarizer, sibling of `project_scene` (374 files, 18 custom Resource classes). Carry into the design (stance rules 5/8): new surfaces label **static vs live** values the way `project_setting` does; `project_index` gains a one-line freshness read (map mtime vs files changed since). First action: gantry:draft the design doc.
5. **Batch J — verification upgrade** (spike). Unknown to resolve: connect to the editor's built-in GDScript LSP (port 6005; also runs windowless via `--headless --editor --lsp-port`) and verify it returns analyzer-grade diagnostics (type errors + warnings `--check-only` can't see, with autoloads resolved) against the 4.6.2 pin; it accepts multiple simultaneous clients. If the spike holds: LSP-backed `godot_check` with `--check-only` fallback + a project-wide error-sweep tool (didOpen-walk every `.gd`).
6. **Batch K — runtime game bridge** (gated on Phases 6 + 8: builds on bridge auth/framing). Done = injected-autoload bridge into the running game (zero addon footprint, injected at launch; reuses the editor-bridge protocol + auth): input simulation via `Input.parse_input_event`, live tree/state inspection, incremental error/log cursors, game screenshot via a windowed off-screen run (headless capture is a verified dead end — the dummy driver discards all rendering). The field's table-stakes loop we lack (9+ servers ship input sim). Carry into the design (stance rules 3/4): runtime family named `game_*` and registered behind a profile key resolved at startup only. First action: design doc.

## Quick fixes (clear in one pass)

Small, self-contained chores that need no plan and aren't worth their own thread. Capped at 5 — overflow means clear some or promote one out, so this stays a batch and never a second backlog. Add with `/claudhd:quick <text>`, clear them in one focused pass with `/claudhd:quick`. The active thread has right of way: clear these between threads, not mid-thread. A fix that turns out to need real thinking gets kicked back to IDEAS.md.

- Add per-call response-size logging to server.py (tool name + response chars, one log line per call) + a tiny report script — feeds stance rule 10 below.

## Idea flow (do not open a new chat)

New idea mid-task: `/claudhd:idea <text>` records it in IDEAS.md so you can keep working. `/claudhd:harvest` backfills ideas from past sessions you never recorded. `/claudhd:triage` clears the inbox. Finished work is recorded in SHIPPED.md via `/claudhd:shipped`.

## Loose ends

- **F-10 housekeeping:** `docs/CURRENTNESS_AUDIT.md` + `docs/RUNTIME_VERIFICATION_QUEUE.md` were committed (`885a579`) but may still carry placeholder `<DATE>`/`<path>` content — fill or remove before they rot.
- ~~**SHIPPED.md** current through Phase 4~~ — RESOLVED 2026-07-03: brought current through Phase 6.6 + the procgen family (`efffa8b`).

## Standing stance — tool surface + token budget

Set 2026-06-10, while the server has **zero external users** — naming, ordering, and protocol changes are free until that changes. Every batch design and review should check against these.

1. **Never rollup, never thin docstrings.** The grounding/edit/test core stays first-class per-tool; docstrings ARE the agent-facing grounding (avg ~220 chars/tool today — already lean). The field's op-enum rollup pattern is rejected.
2. **Growth rule: variant = param, new noun = new tool.** `project_setting(resolve=True)` is the pattern. This is what actually prevents the 150-tool accretion the field hit; everything else is relief valves.
3. **Family flags at batch K.** Situational tool families (runtime bridge; optionally the editor bridge) register behind a profile key, resolved at **startup only**, never mid-session (prompt-cache stability).
4. **Settle permanent tool naming in Phase 6.6** (SHIPPED 2026-07-03): family prefixes — `godot_*` engine grounding + validate/edit/test, `project_*` project grounding, `editor_*` live editor bridge, `game_*` batch-K runtime bridge, **`procgen_*` procedural-generation tooling** (decided 2026-07-03 for the procgen suite; `worldgen_*` rejected as too narrow for the tileset-build tools). Once external users exist, renames become breaking changes.
5. **Responses are budgeted.** Compact by default, a param (`full=true` style) to go deep; anything that can exceed ~2k tokens returns a summary + file handle (the Phase-G screenshot decision, generalized); stream-shaped data (runtime logs/errors) uses incremental since-last-call cursors (batch K requirement). Results dwarf definitions: 30-50 calls/session × 1-2k tokens each vs ~2.6k of definitions once.
6. **Shared semantics live once in the MCP server `instructions` block** (res:// path rules, the "Refused" containment shape, `# lint: ignore` syntax, the ground → linted edit → test-to-confirm loop) — not repeated across 30 docstrings.
7. **Retry elimination is a token feature.** Misleading errors and bad rankings are budget bugs, not polish: every confusing verdict costs a full agent round-trip. Canonical examples from the audit: M1/C5 (env failure reported as "script does not parse" sends the agent into a fix-nothing loop), C21 (exact search match buried below truncation forces re-queries).
8. **Precomputed artifacts carry provenance and get a doctor line.** Stamp every generated artifact (API dump, docs cache, rendered agent templates, the codebase map `project_index` serves) with what it was generated from (engine version / date / commit). Doctor checks each for drift (C17 binary-vs-dump, C19 version-keyed docs cache already queued; add a `project_index` freshness read — map mtime vs files changed since). Borrowed from Gantry: artifact + cheap reconciliation pass + visible trust tier, instead of silent trust or constant regeneration.
9. **MCP resources: parked.** `godot://` read-only URIs are off-spec-cheap but client support is weak; watch, don't build.
10. **Instrument before optimizing further.** Per-call response-size telemetry (quick fix queued above); re-measure definition cost each batch (baseline 2026-06-10: 30 tools, ~6.5k docstring chars, ~2.6k tokens with schemas). Act on telemetry at >50 tools or >6k definition tokens — trim the actually-fat tools, not guesses.

## Leaving this file when you stop

Before you walk away, or whenever you switch context, make the "Next physical action" line true and tiny. That one line is what lets you stop mid-thought and lose nothing. The quick way: run `/claudhd:wrap` and it reconciles this file for you - checks off what's done, writes the next action, and closes out loose ends.
