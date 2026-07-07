# Biome-world (procgen v3) TOOLS deltas — Implementation Plan

Source design: `docs/design/biome-world.md` (§3 only; §4 is GAME-repo work, reconciled separately in `squareds/project1`, NOT planned here)
Conventions read: no root `CLAUDE.md`/`AGENTS.md`/`CONVENTIONS.md` exist in this repo; conventions inferred from the v2 design + plan (`docs/design/procgen-tools.md`, `docs/design/procgen-tools.plan.md`) and confirmed directly against `src/godot_mcp/procgen.py`, `src/godot_mcp/server.py`, `scripts/ci_smoke.py`, and the existing `tests/test_procgen_*.py` suite.
Verification command(s):
- tests: `./.venv/Scripts/python.exe -m pytest tests/ -q`
- lint: `./.venv/Scripts/python.exe -m ruff check src/godot_mcp tests`
- types: `./.venv/Scripts/python.exe -m mypy` (config in `pyproject.toml`, `files = ["src/godot_mcp"]`)
- roster gate: `./.venv/Scripts/python.exe scripts/ci_smoke.py` (exact `EXPECTED_TOOLS` set)

## Summary

Five phases. v3 forks the terrain law from v2's water-bottom (islands-only) to a biome-layer law (one contiguous all-land world, biomes meet through transparent-edge transition panels). The TOOLS side is small: three of the four §3 items are largely config-shape + investigation work reusing existing `procgen_tileset_build`/`_STRATEGY_TABLES`/`procgen_terrain_audit`, and one is a genuinely new headless (actually pure-PIL, seed-deterministic) tool `procgen_biome_field` that previews the CA blob field. Phase 1 confirms the reuse claims and lands the biome-set config shape; phases 2-3 are the small config/audit deltas; phase 4 is the new field-preview tool; phase 5 is docs + roster wiring.

Grounding done at plan time (verified against `src/godot_mcp/procgen.py`, 2026-07-06):
- `minifantasy_edges_table()` `(1,1)` cell already carries the empty `()` corner signature — the "transparent center at the (1,1) empty-signature class" the design's §5 claims. Confirmed at `_MINIFANTASY_EDGES_LAND_CORNERS[(1,1)] = ()`.
- `_cell_has_pixels()` (the sheet scan) tests `img.get_pixel(...).a > 0.0` anywhere in the cell. It does NOT assume opaque *edges*; a transition tile whose "outside" is transparent still has opaque land pixels, so it scans identically to a land/water tile. **This is the core "does the builder need a change?" question and the answer is grounded: NO scan change.** (Confirmed in code; a golden build test in Phase 1 proves it end to end.)
- The animation path (`set_tile_animation_columns/separation/frames_count/frame_duration/mode`) is orthogonal to pixel opacity — it operates on grid coords, never samples alpha. So the transparent-edge block does not perturb the animation code path either.
- `_STRATEGY_TABLES` already contains `minifantasy_edges`; the transition panel *is* the same 3x5 corner-Wang block. No new strategy table is required for the panels themselves.

## Blockers / Open Questions

None block Phase 1. Phase 1 is a confirmation-plus-config phase that stands on reuse claims already grounded above.

Cross-repo dependencies (informational — these are §4 decisions the tools track but do not implement; do NOT plan the §4 side here):
- **B1 (affects Phase 2 scope, not Phase 1):** the game-side matcher predicate flip ("is land" → "is biome Y") ships game-side (`systems/worldgen/terrain_matcher.gd`, spec-locked in `tests/test_terrain_matcher_spec.py`). The tools only *emit* peering bits and *audit* coverage; the tools never run a matcher. So the flip does not change tool code, but Phase 2 must confirm the biome-set config still emits the same corner-bit signatures the game matcher will read. This is a confirm, not a build.
- **B2 (affects Phase 3 only if 3.4 turns out YES):** whether `procgen_terrain_audit` needs biome-set/transition coverage reporting depends on what the game's per-biome-pair transition art coverage contract actually is. Phase 3 opens by deciding YES/NO from the design; if the design does not pin a per-pair coverage requirement, 3.4 resolves to "no audit change needed" and Phase 3 is doc-only. This is a plan-time investigation the design explicitly flagged ("confirm at plan"), resolved inside Phase 3, not a human blocker.
- The RUNTIME biome-field generator, hex map, fog shader, streamer, and save format are all §4 game-side and out of scope. Phase 4's `procgen_biome_field` is the TOOLS-side authoring/verification aid only; it computes its own field in Python (seed-deterministic CA), needs NO game hook, and shares the field *algorithm parameters* with the game so authored params transfer — but the two implementations are independent (a port, not a shared library), same posture the v2 plan took for the S1 matcher helper.

## Phase 1: biome-set config shape + transparent-transition build confirmation

**Status:** committed
**Amendment (2026-07-06, per phase-1 review):** exit criterion corrected. A transparent-outside block builds identically to opaque for all LAND tiles (bits + terrain sets), but the transparent water-center (1,1) correctly yields one fewer tile than the opaque water-center, so the criterion reads "identical land bits + terrain sets + expected off-by-one tile", not "same tile count". Also brought explicitly in scope for this phase: the `.gitignore` addition of the transient `.gantry/active-phase.json` sentinel (repo hygiene the review surfaced).
**Goal:** Land the declarative biome-set config (transition panels + priority order + per-biome coastline block in one config) for `procgen_tileset_build`, and prove in a golden build test that a transparent-outside transition block builds identically to the v2 land/water block with no builder code change.
**Files:**
- `src/godot_mcp/procgen.py` (config validation only — extend `validate_config` to accept the biome-set config shape: a priority-ordered roster of biomes, each with its `minifantasy_edges` transition-panel `terrain_assign` and its coastline `terrain_assign`; NO changes to `compose_build_script`'s scan/animation paths — the grounding above says none are needed, and this phase's test proves it)
- `tests/test_procgen_biome_config.py` (NEW — pure-Python config-validation tests: valid biome-set config normalizes; priority order preserved; missing/duplicate biome in roster errors; a transition-panel assign and a coastline assign on the same biome both validate)
- `tests/test_procgen_biome_build.py` (NEW — binary-gated golden build test, mirrors `tests/test_procgen_build.py`: synthesizes a tiny fixture atlas via Godot's `Image` with a 3x5 block whose "outside" pixels are TRANSPARENT instead of blue, writes a biome-set config, runs the real headless build, asserts the `.tres` reports IDENTICAL land bits and terrain-set counts to the equivalent opaque-outside block — the empirical proof that transparent edges change nothing in the builder's land-tile handling. One expected, isolated delta: the water-center (1,1) cell — opaque-blue creates it as a water tile, transparent (alpha 0) is skipped by the scan, so the transparent block has exactly one fewer tile. That is the intended v3 behavior: the transparent center is the hole where the biome below shows through, so it correctly must NOT materialize, and the base biome fill supplies that empty-signature class. Tile counts therefore differ by exactly that one cell; land bits + terrain sets are identical.)
- `docs/design/biome-world.md` — NOT edited (source of truth; do not touch)
- `.gitignore` — add the transient `.gantry/active-phase.json` sentinel ignore (repo hygiene surfaced by the phase-1 review; the sentinel is written per phase and cleared after review, so it must never be tracked)
- `docs/design/biome-world.plan.md` — this plan file itself, carrying this phase's orchestrator writes only: the `**Status:**` transitions (built → ready → committed) and the review amendment note above. The implementer never edits it; these are gantry orchestrator bookkeeping, not implementation changes.
**Verification:** `./.venv/Scripts/python.exe -m pytest tests/test_procgen_biome_config.py tests/test_procgen_biome_build.py -q` green (the build test skips cleanly when no Godot binary resolves, same guard as `test_procgen_build.py`); full `pytest tests/ -q`, `ruff`, and `mypy` stay green.
**Exit criteria:** A biome-set config validates in Python and produces a loadable `.tres` whose transition-panel tiles carry the expected corner-Wang bits; the golden build test proves transparent-outside and opaque-outside produce IDENTICAL land bits + terrain sets (the §3.1 "does the transparent-center block need a builder change?" question is answered NO with a passing test). The transparent water-center cell correctly yields exactly one fewer tile than the opaque block — the intended v3 blend behavior, not a discrepancy — so the test asserts equal land bits/terrain-sets and the expected off-by-one-cell tile count, not equal tile counts. If the test had surprised us with a difference in LAND handling, a specific isolated builder fix would be scoped as its own micro-phase before continuing.
**Blockers:** none.
**Wired-by:** phase 5 (the biome-set config shape is exercised by the tool but only documented + roster-confirmed in phase 5; `procgen_tileset_build` itself is already registered, so no new tool surface is added here — this phase extends an existing tool's accepted config).

## Phase 2: priority-order + coastline pass assignment in the biome-set config

**Status:** pending
**Goal:** Make the biome-set config express the full v3 biome-layer draw contract as declarative data (priority `desert > ice > swamp > plains`, water/lakes as base below, each biome's coastline block for land↔lake shores), so a single config builds a complete multi-biome tileset the game's two draw passes consume.
**Files:**
- `src/godot_mcp/procgen.py` (config normalization: resolve the roster's priority order into a stable, serialized order in the normalized config; ensure each biome's transition-panel assign and coastline assign resolve through the existing `_resolve_assign_bits` unchanged — the panels reuse `minifantasy_edges`, the coastline reuses the same v2 land/water block. No new strategy table; no `compose_build_script` bit-assignment change.)
- `tests/test_procgen_biome_config.py` (extend: priority order round-trips deterministically through validate/normalize; a config with both a transition-panel assign and a coastline assign per biome resolves both; an out-of-roster priority entry errors)
- `tests/test_procgen_biome_build.py` (extend: a two-biome fixture config builds a `.tres` carrying both biomes' panel tiles and coastline tiles, reload count matches)
**Verification:** `./.venv/Scripts/python.exe -m pytest tests/test_procgen_biome_config.py tests/test_procgen_biome_build.py -q`; then `procgen_terrain_audit` on the built two-biome `.tres` reports clean coverage per biome terrain set (proves the emitted bits are the corner signatures the game matcher will read — the B1 confirm). Full suite + ruff + mypy green.
**Exit criteria:** One biome-set config builds a multi-biome tileset with correct per-biome transition and coastline bits, priority order is deterministic in the normalized output, and an audit of the result is clean. §3.2 water animation is confirmed here as pure config usage (an existing `[[animation]]` group on the lake/water biome, `mode="default"`) with NO new tool code — asserted by a fixture config that carries an animated water biome and audits clean for animation sync.
**Blockers:** depends on Phase 1's config shape. B1 (matcher predicate flip) is a cross-repo confirm resolved by the clean audit, not a build dependency.

## Phase 3: terrain-audit biome-set coverage (3.4 investigation → resolve)

**Status:** pending
**Goal:** Decide from the design whether `procgen_terrain_audit` must report biome-set / transition coverage the way it reports single-terrain coverage, and either add that reporting or record that no change is needed.
**Files:**
- `src/godot_mcp/procgen.py` (ONLY if the investigation resolves YES: extend `_audit_report`/`_format_audit_report` to summarize per-biome transition-panel coverage across the biome roster — reusing `expected_signature_set` and the existing per-terrain-set coverage machinery, since each biome is already its own terrain set under the v2 audit. If NO: no code change; the existing per-terrain-set audit already covers each biome's panel block because a biome-set tileset is N single-terrain sets.)
- `tests/test_procgen_biome_audit.py` (NEW — if YES: assert the multi-biome tileset from Phase 2 reports per-biome coverage and flags a deliberately-missing transition class; if NO: a test asserting the existing per-terrain-set audit already gives complete per-biome coverage on a multi-biome tileset, which is the evidence that no new reporting is needed)
**Verification:** `./.venv/Scripts/python.exe -m pytest tests/test_procgen_biome_audit.py -q` plus full suite green. The resolution (YES with new reporting, or NO with the existing audit shown sufficient) is written into `docs/design/procgen-tools.md`'s S-verdict section style — NOT into `biome-world.md` (source design is not edited).
**Exit criteria:** §3.4 is resolved with evidence: either the audit reports biome-set coverage and a test catches a missing transition class, or a test demonstrates the existing per-terrain-set audit already covers every biome and the design note records "no audit change needed."
**Blockers:** B2 (whether a per-pair transition coverage contract exists) is resolved inside this phase from the design; it is not a human blocker. Depends on Phase 2's multi-biome tileset for its fixture.

## Phase 4: `procgen_biome_field` — headless (pure-PIL) blob-field preview tool

**Status:** pending
**Goal:** Add a new tool that renders the blob-biome field (radial/noise seed + cellular-automata majority smoothing, 3 CA passes, seed-deterministic, per bake region with a 4-cell margin computed-but-not-committed) so field params can be authored and eyeballed before they go into the game.
**Files:**
- `src/godot_mcp/procgen.py` (NEW: pure-Python field generator — seedable RNG, radial/noise initialization, 3-pass CA majority smoothing, per-region computation with margin = CA passes (3) + matcher ring (1) = 4 cells, margin cells computed but excluded from the committed region so adjacent regions seam-match deterministically; NEW `biome_field(...)` entry returning `[summary_text, MCPImage]` following the `atlas_grid` return contract — one filled square per cell colored by biome, seed + region legend, ascii fallback inline in the summary for chat review; pure Pillow, NO headless Godot, mirroring `atlas_grid`'s no-Godot posture)
- `src/godot_mcp/server.py` (NEW: register `procgen_biome_field` with `@mcp.tool(structured_output=False)` — the same decorator `procgen_atlas_grid` uses for its list/image return)
- `tests/test_procgen_biome_field.py` (NEW — pure-Python, no binary gate: same seed + same region → byte-identical field (determinism); a region and its neighbor agree on their shared 4-cell margin band (seam-match); the returned content carries real `ImageContent` not just a path, mirroring `test_procgen_atlas_grid.py`'s `ImageContent`/`TextContent` assertions; a malformed region/param returns a clean error string, not a raise)
- `scripts/ci_smoke.py` (add `"procgen_biome_field"` to `EXPECTED_TOOLS` in the SAME commit that registers the tool — the roster gate fails otherwise)
**Verification:** `./.venv/Scripts/python.exe -m pytest tests/test_procgen_biome_field.py -q` green; `./.venv/Scripts/python.exe scripts/ci_smoke.py` passes the exact-roster assertion with the new tool present; full suite + ruff + mypy green.
**Exit criteria:** `procgen_biome_field` renders a deterministic field for a given seed, two adjacent regions seam-match on their margin band, the tool returns real MCP image content + an ascii fallback, and the tool is in the pinned roster. Determinism and seam-match are proven by tests, not eyeball; the image is the human authoring aid on top.
**Blockers:** none. This is the tools-side field work; the game-side runtime generator (§4) is out of scope and independent (shares algorithm params, not code — a port).
**Wires:** registers a new public tool `procgen_biome_field` and wires it into the `ci_smoke` roster in the same commit.

## Phase 5: docs + roster reconciliation

**Status:** pending
**Goal:** Document the biome-set config shape and the new field-preview tool, and confirm the tool roster/README are consistent, so a cold session can read the v3 tools surface without reverse-engineering it.
**Files:**
- `README.md` (add `procgen_biome_field` to the tool table; extend the `procgen_tileset_build` row to note the biome-set config shape; extend the `procgen_terrain_audit` row only if Phase 3 resolved YES)
- `docs/design/procgen-tools.md` (append a v3 note / verdict section recording: the transparent-transition-no-builder-change confirmation, the §3.2 config-only water-animation confirmation, the §3.4 resolution, and the new `procgen_biome_field` tool — this is the running verdict doc, the same one v2's S1/S3 verdicts live in; `biome-world.md` is NOT edited)
- `tests/test_docs.py` (extend/confirm: if it asserts README tool-table ↔ roster consistency, ensure `procgen_biome_field` is covered; if it does not, add a check that the roster and README table agree)
- `scripts/ci_smoke.py` — verify (should already carry `procgen_biome_field` from Phase 4; this phase only confirms no drift)
**Verification:** `./.venv/Scripts/python.exe -m pytest tests/test_docs.py -q` and `./.venv/Scripts/python.exe scripts/ci_smoke.py` green; full suite + ruff + mypy green.
**Exit criteria:** README tool table, `ci_smoke` roster, and the registered tools all agree; the v3 tools deltas and their confirmations are recorded in the running verdict doc; `docs/design/biome-world.md` is untouched.
**Blockers:** depends on Phases 1-4 landing.

## Cross-cutting concerns

- **Tool roster (exact-set gate).** `scripts/ci_smoke.py`'s `EXPECTED_TOOLS` is an authoritative exact set; adding `procgen_biome_field` without updating it fails CI, and updating it without registering the tool also fails. **Ordering:** the roster edit MUST land in the same commit as the `server.py` registration (Phase 4). Rollback: revert both together.
- **`server.py` tool registration surface (public MCP contract).** `procgen_biome_field` is a new public tool. It must use `@mcp.tool(structured_output=False)` to match the `procgen_atlas_grid` list/image return (a structured-output tool cannot return the `[text, Image]` list). **Ordering:** Phase 4. Affects: any MCP client listing tools; the README table; the `ci_smoke` roster; `test_docs.py` if it cross-checks the table.
- **Config schema shape (build↔author contract).** The biome-set config is a new shape consumed by `procgen_tileset_build`'s `validate_config`. It is additive — v2 configs (single-terrain, water-bottom) must still validate and build byte-for-byte unchanged (the `.tres` golden tests in `test_procgen_build.py`/`test_procgen_audit_build.py` are the regression guard). **Ordering:** Phases 1-2 introduce it; Phase 1's first act is confirming the existing golden build tests still pass so the new shape does not perturb the old path. Rollback: the new config keys are opt-in, so removing the biome-set validation branch restores v2 behavior.
- **The v2/v3 law fork (documentation contract, NOT a code migration).** v3's biome-layer law replaces the water-bottom law *conceptually*, but the TOOLS implement it as N single-terrain sets (one per biome) plus a coastline block for lakes — the same primitives v2 already builds. There is NO tileset data-format migration and NO breaking change to `compose_build_script`'s per-tile emission. The audit's "one terrain per terrain set" rule still holds per biome. This is called out so an implementer does not mistake the law fork for a schema migration: it is not. **Ordering:** documented in Phase 5's verdict note.
- **Cross-repo matcher-predicate flip (B1) and runtime field generator (§4).** These ship in `squareds/project1`, spec-locked by `tests/test_terrain_matcher_spec.py` in THIS repo. The tools never run a matcher or the runtime field generator; they emit bits (Phases 1-2) and preview the field (Phase 4) independently. **Ordering:** the clean audit in Phase 2 is the tools-side confirmation that the emitted signatures match what the flipped game matcher will read. Do not implement the §4 side here.
- **No new external dependency.** `procgen_biome_field` uses Pillow (already a dependency, used by `atlas_grid`) and the stdlib RNG; no new package. Keeps `pyproject.toml` dependencies unchanged.
