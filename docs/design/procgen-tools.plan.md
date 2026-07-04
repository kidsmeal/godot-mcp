# Plan: godot-mcp Procgen Tool Upgrades

**Status: v2, 2026-07-03 (v1 2026-07-02). Written for a fresh implementation session (target model: Opus 4.8) with no context from the design sessions.** v2 changes: water-bottom law adopted, in-house matcher is the decided backend (phase 3 reworked from a BetterTerrain adoption gate to a matcher spike), tile-animation requirements added to phases 1-2, 4.7 recheck folded in. Read first: `procgen-tools.md` (the research findings, the law, and tool rationale; do not re-research what it already verified), then this plan. The game-side consumer is the game repo's `docs/plan_island_generation.md` (`C:\Users\atk67\Documents\squareds\project1`); this plan's phases 1-3 gate that plan's phase 3.

## Context you do not have

- The target repo is the in-house MCP server at `C:\Users\atk67\Documents\godot-mcp` (Python, FastMCP, stdio). It already exposes ~24 tools: engine grounding (`godot_class`, `godot_search`), project grounding (`project_find_files`, catalogs), validation (`godot_check`, `godot_validate`, `godot_run_tests`, `godot_run_script`, lint), and script editing with parse-check + rollback. It drives headless Godot via the CLI (`GODOT_BIN`, default `godot` on PATH; 4.6.2 standard build on this machine, 4.7 incoming — engine facts rechecked against 4.7-stable 2026-07-03, nothing moves) and reads a per-project `godot-mcp.toml` (`GODOT_PROJECT` env). New-project onboarding is `setup.ps1 -Project <path>`.
- **Phase 0 of this plan is reading that repo.** Match its existing patterns exactly: how tools are registered, how it composes and runs temp GDScript, how results are truncated/formatted, how errors surface. Do not invent a parallel style.
- The game project (may not exist yet as a repo; the design docs live at `C:\Users\atk67\Documents\squareds\project1`) is an 8x8 pixel game using Minifantasy packs at `C:\Users\atk67\Documents\minifantasyassets`. Test against `Minifantasy_ForgottenPlains_v3.6_Commercial_Version` (subfolder `Minifantasy_ForgottenPlains_Assets/Tileset` + `props`).
- Verified engine facts (sources and full nuance in `procgen-tools.md` §1, all 3-vote verified 2026-07-02): TileSet building is fully headless-scriptable (`create_tile` per cell, `get_tile_data` alt 0, terrain sets/peering bits/physics/nav/custom-data all scriptable, `ResourceSaver` works headless, terrain_set must be set on a tile BEFORE terrain/bits, the editor's auto-create-tiles has no script API so scan the sheet yourself via `Image` alpha checks). The built-in terrain solver is buggy (#76493, #89844) and `set_cells_terrain_path` is NOT a workaround (refuted): none of these tools may call the built-in solver. Headless rendering is an unverified-but-credible no (proposal #5790, dummy rasterizer; see the research record's unverified-leads section): previews are therefore composed in Python with PIL from dumped data + source PNGs, which depends on engine rendering not at all.
- Decisions locked 2026-07-03 (full statements in `procgen-tools.md` §1): the **water-bottom law** — every TileMapLayer autotiles itself-vs-empty only, one terrain per terrain set, edge/corner tiles are biome+water composites carrying 2-frame water animation, in-window water is painted animated tiles in `TILE_ANIMATION_MODE_DEFAULT` (the engine starts all tile animations simultaneously, 4.7 class docs; the coastline sync contract depends on it). The **in-house matcher is the decided backend**; BetterTerrain is fallback only (it stores terrain data in `set_meta()`, not engine terrain bits — a coupling we rejected). The solver ban holds on 4.6 and 4.7 alike.
- Windows machine. Paths with spaces exist (`Minifantasy_UI _Overhaul_v1.0` has a real stray space). Always quote; prefer pathlib.

## Phase 0: recon and harness

**Tool family (decided 2026-07-03):** all 6 tools register under the **`procgen_*`** prefix — `procgen_tileset_build`, `procgen_terrain_audit`, `procgen_worldgen_preview`, `procgen_island_preview`, `procgen_chunk_lint`, `procgen_gen_smoke` (rationale + the shorthand→registered mapping in `procgen-tools.md` §2). This joins the families settled in Phase 6.6 (`godot_*`/`project_*`/`editor_*`). Add each new tool to `scripts/ci_smoke.py`'s exact-roster `EXPECTED_TOOLS` set in the same commit that adds it (Phase 4 pinned the roster; a tool missing from it fails CI).

Read the mcp repo (`main.py` and however tools are modularized), then add a `procgen` tool module in the same style, registered behind the same config plumbing. Add one throwaway `procgen_ping` tool proving registration, then delete it in the same phase once the first real tool lands. Decide (and write down in the module docstring) the temp-script pattern: compose GDScript to the OS temp dir, run via the existing headless-run helper, parse JSON from stdout between sentinel lines (match whatever `godot_run_script` already does).

Exit criteria: module registered, a trivial headless round-trip (GDScript prints JSON, Python parses it) works on the capsulecastle project profile.

## Phase 1: `tileset_build`

**Carry-in from the Phase 0 review (2026-07-03) — harden the harness here, the first tool with a large real-data payload:**
- **Sentinel-collision:** the P0 probe parses JSON between literal `PROCGEN_JSON_BEGIN`/`PROCGEN_JSON_END` markers with a non-greedy regex. That truncates early if a payload's JSON ever *contains* the literal end-marker (plausible once tools dump arbitrary project data — file paths, config values, atlas names). Before copying the pattern, switch to a collision-resistant sentinel (a per-run random nonce appended to the marker) or length-frame / base64 the JSON. Do this in P1 so all 6 tools inherit the hardened version.
- **Docstring accuracy:** `procgen.py`'s docstring says the payload is printed "on ONE line," but the parser already tolerates multi-line (`re.S`). When P1 copies the pattern, relax that wording to "single- or multi-line between the sentinels" so a copier doesn't needlessly cram output. Doc-only.

`tileset_build(config_path: str, out_path: str) -> report` where config is a TOML/JSON file in the game repo describing one TileSet:

```toml
[tileset]
tile_size = [8, 8]
[[atlas]]
id = "plains_ground"
texture = "res://art/plains/ground.png"
margins = [0, 0]
separation = [0, 0]
scan = "non_transparent"        # or "all", or explicit [[atlas.tiles]] list
[[animation]]                    # tile-animation groups; frame regions are RESERVED, never scanned as tiles
atlas = "plains_ground"
base_region = [[0, 4], [7, 5]]   # inclusive tile-coord rect of BASE tiles (frame 0)
frames = 2
frame_offset = [8, 0]            # frame N sits at base + N * offset, in tile coords
duration = 0.6                   # seconds per frame
mode = "default"                 # "default" = engine-synchronized start (REQUIRED for water-bearing tiles); "random_start" for decor only
[[terrain_set]]
mode = "match_corners_and_sides" # or match_corners / match_sides
terrains = [ { name = "grass", color = "#4c8f3c" } ]  # ONE terrain per terrain set (water-bottom law; validation errors on more)
[[terrain_assign]]               # peering-bit assignment
atlas = "plains_ground"
strategy = "blob47"              # template mapping for standard autotile blob layouts
origin = [0, 0]                  # where the blob block starts in the atlas
terrain = "grass"
background = "empty"             # signatures are grass-vs-empty; water is a separate dumb-fill layer, never a peer terrain
# strategy = "explicit" with per-tile bits is also supported
[physics]
default_full_square = ["grass"]  # terrains that get a full 8x8 collision polygon on layer 0
[custom_data]
layers = [ { name = "biome_id", type = "string" }, { name = "move_cost", type = "int" } ]
```

Implementation: Python validates the config (errors on >1 terrain per terrain set, and on `mode != "default"` for any animated tile that carries a terrain — water-bearing edges must sync), composes one GDScript that (in this order, the order is load-bearing): creates `TileSet`, adds custom-data/physics/nav layers, adds terrain sets and terrains, per atlas creates `TileSetAtlasSource` (texture, `texture_region_size`), applies the animation map FIRST and marks every frame region reserved (frame regions consume real atlas grid space — see `has_room_for_tile`'s animation params; a naive scan would collide with them), scans the remaining sheet (`Image.load`, per-cell region alpha test) or takes the explicit list, `create_tile` per base cell plus `set_tile_animation_columns/frames_count/frame_duration/mode` for animated groups, then per tile `get_tile_data(coords, 0)`: set `terrain_set` FIRST, then `terrain`, then peering bits per strategy, then collision polygons (edge tiles get per-signature-class polygon templates — straight edge / inner corner / outer corner — defined once in Python, reused across biomes since the Minifantasy edge geometry is consistent pack to pack) and custom data; finally `ResourceSaver.save(tileset, out_path)` and a reload sanity check (`ResourceLoader.load`, count tiles). GDScript prints a JSON report (tiles created per atlas, animated groups baked, terrains, bits assigned, skipped transparent cells, warnings).

The `blob47` strategy is a data table in Python (the standard 47-tile blob layout mapping grid offsets to peering-bit sets for match_corners_and_sides). Build it once, test it, and support `blob16_sides` and `blob16_corners` variants the same way. Minifantasy sheets that do not follow a blob layout use `strategy = "explicit"`; do not guess layouts.

Exit criteria: builds a plains TileSet from the real ForgottenPlains sheet; report matches expectations; the `.tres` loads; a golden-file test config in the mcp repo's test suite runs green headless. One manual editor-open confirmation by the user is worth requesting in the report text.

## Phase 2: `terrain_audit`

`terrain_audit(tileset_path: str, terrain_set: int = -1) -> report`. GDScript loads the TileSet and dumps per-tile terrain data plus animation data; Python computes and reports, per terrain: the expected signature set for the set's mode under the water-bottom law (itself-vs-empty only, ~47 classes for corners+sides; compute from the mode's valid bits, do not hardcode counts), which signatures are covered / missing / duplicated (two tiles with identical signatures: allowed, flag as variants — the matcher's seeded pick uses them), tiles with `terrain != -1` but `terrain_set == -1` (broken ordering), terrain sets with more than one terrain (law violation: error), unused tiles (no terrain, no custom data), and the animation sync lint: every animated terrain tile shares identical frames/duration and `mode == DEFAULT` (a random-start water tile desyncs coastlines: error, not warning). Output: markdown table + a machine `coverage` dict in the result (the in-house matcher in the game repo consumes the same dump format; keep the dump shape stable and documented).

Exit criteria: audit of the phase-1 plains TileSet is clean; a fixture TileSet with a deliberately missing combo and a broken-ordering tile is caught by tests.

## Phase 3: spike S1, matcher + audit end-to-end on the real plains tileset (GATE)

(Reworked 2026-07-03: the in-house matcher is the decided backend and BetterTerrain is fallback only, so this spike validates the decided path on real art instead of gating an adoption.)

Using the phase-1 plains TileSet and the phase-2 audit dump: a throwaway headless SceneTree script builds a toy landmass mask (roughly 20x20 with a bay and an interior pond), resolves every ground cell through the matcher algorithm — 8-neighbor same-layer occupancy signature, exact-match against the audit `coverage` table, seeded pick among variants (tie-break by atlas coords order), fallback to the full-interior tile on miss with a debug log — writes the cells, dumps them, and asserts interior / straight-edge / inner-corner / outer-corner picks against hand-computed expectations. Time a full 96x96 resolve (budget: comfortably inside the game plan's 150ms materialize budget; the #80635 thread's plain-GDScript numbers suggest large headroom). Render the toy island via the T4 stamping path (or a minimal precursor) for one human eyeball pass on the coastline, animated edges at frame 0.

The matcher itself ships in the GAME repo (`systems/worldgen/terrain_matcher.gd`, game plan phase 3), not in the mcp; this spike's script is throwaway evidence, but write its signature-computation helper as if it were the matcher's core so the game implementation is a port, not a redesign.

Write the verdict into `procgen-tools.md` under an "S1 verdict" heading with timings and the eyeball render path. Only if this fails in a way the audit cannot explain does the parked BetterTerrain fallback get evaluated (vendor `Portponky/better-terrain`, record the commit SHA; note its terrain data lives in `set_meta()`, not engine terrain bits, so T1 would need a second export path — that cost is why it is the fallback).

Exit criteria: verdict recorded with evidence (timings, failures if any). This unblocks the game plan's phase 3.

## Phase 4: `worldgen_preview`

`worldgen_preview(world_seed: int, out_png: str = "") -> report + image path`. Requires the game repo's `tools/dev_scripts/dump_worldgen.gd` (game plan phase 2 provides it; until then the tool errors with a clear "game hook missing" message). Runs it headless with the seed, parses the JSON dump (15x15 records + biome map colors), renders with PIL: one filled square per tile (biome `map_color`), hub marker at center, dungeon markers, thin ring-band boundary lines, seed + palette legend; default out path under the game repo's `test-results/worldgen/`. Also return a 15x15 ascii map (one letter per biome) inline in the tool result so chat review works without opening files.

Exit criteria: three different seeds render; colors match `BiomeDef.map_color`; ascii and PNG agree.

## Phase 5: `island_preview`

`island_preview(coords: [x, y], world_seed: int, out_png: str = "") -> report + image path`. Game hook `tools/dev_scripts/dump_tile.gd` (game plan phase 3) materializes one tile headless and dumps per-layer cells as `{layer: [[x, y, source_id, atlas_x, atlas_y, alt]]}` plus the tileset's atlas texture paths and entity marker list. Python stamps 8x8 regions from the source PNGs into a layered image (layer order: water, ground, detail, props, overhang), overlays entity markers (colored dots + id labels toggle), scales x3 nearest-neighbor.

Exit criteria: a plains rich tile and a ruin tile render and are visually distinguishable; a regression test snapshots cell-dump hashes, not pixels.

## Phase 6: `chunk_lint` and `gen_smoke`

- `chunk_lint(template_path or dir) -> report`: loads `ChunkTemplate` resources headless, validates: expected pattern layers present, size within `WorldGenConfig` chunk bounds, every referenced source/atlas coord exists in the biome's TileSet, no props on water-only cells, `biome_tags` reference real biome ids. Batch mode over a directory.
- `gen_smoke(world_seed: int, sample_tiles: int = 3) -> report`: runs the game's worldgen twice (record-level diff must be empty), materializes N sample tiles twice each (cell-dump hash diff must be empty), reports timings against the game plan's budgets (paint < 50ms, materialize < 150ms headless). This is the determinism contract's tripwire; wire it so the game's CI-ish test pass can call it.

Exit criteria: both run green against the game repo once its phases 2-3 exist; `chunk_lint` catches a seeded-bad fixture.

## Cross-cutting

- Every tool: respects `GODOT_PROJECT`/`GODOT_BIN` env exactly like existing tools, parse-checks any composed GDScript before running (existing mcp discipline), writes only to declared out paths + OS temp, never mutates the game repo otherwise, and returns errors as structured reports rather than stack traces.
- Add each tool to the mcp README's tool table and to `setup.ps1`-generated agent docs if that is where the tool list is templated (check during phase 0).
- Pin assumptions in code comments with the issue numbers where behavior is bug-adjacent (#76493, #89844, proposal #5790) so future engine upgrades can be re-audited by grepping.
- Version snapshot: engine facts verified on Godot 4.6.2 (2026-07-02) and rechecked against 4.7-stable (2026-07-03): solver bugs unchanged, PR #108629 not in 4.7 (resolved watch item, see `procgen-tools.md` §4), the only 4.7 terrain changes are editor-UI. `TILE_ANIMATION_MODE_DEFAULT` starts all tile animations simultaneously (4.7 class docs); the water sync contract depends on this — re-verify on any engine bump.
