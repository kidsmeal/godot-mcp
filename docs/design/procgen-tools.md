# Godot MCP Tooling for Biome Island Generation

**Status: v2, 2026-07-03** (v1 2026-07-02). v2 locks the terrain architecture: the water-bottom law (§1), in-house matcher promoted to primary backend, BetterTerrain demoted to fallback, tile-animation requirements added to T1/T2, and the 4.7 recheck folded in (engine solver unchanged; PR watch item resolved). What to add to the in-house godot-mcp (`C:\Users\atk67\Documents\godot-mcp`, Python FastMCP + headless Godot) so tileset setup and biome generation don't require handcoding everything. Grounded in a deep research pass (23 sources, 25 claims adversarially verified 3-vote, 2 refuted, plus one empirical test run on this machine's Godot 4.6.2 binary); **the complete compiled record with every finding, refuted claim, unverified lead, and source is `../research/godot_tilemap_procgen_research.md`**. Findings are snapshots of 2026-07-02; addon/PR statuses are time-sensitive.

## 1. What the research settled

**Tileset building is fully headless-scriptable on stock 4.6.** TileSet is a plain Resource. Tiles are registered per-cell with `TileSetAtlasSource.create_tile()` (the editor's "create tiles in non-transparent regions" convenience has NO script API, so our builder scans the sheet itself); per-tile config goes through `get_tile_data()` (alternative 0 = main tile). Terrain sets, terrains, and peering bits are fully scriptable (`add_terrain_set`, `set_terrain_set_mode` [default MATCH_CORNERS_AND_SIDES], `add_terrain`, `TileData.set_terrain_peering_bit`; terrain_set must be assigned before terrain/bits). Physics, navigation, occlusion, and typed custom-data layers (biome id, movement cost) are all scriptable; `ResourceSaver` works under `--headless`. One version note: `set_physics_layer_collision_priority` exists only from 4.4 (fine on 4.6). Direct `.tres` text writing is also viable (TileData serializes as pseudo-properties like `0:0/0/terrain_set`) but the API path is the supported one.
Sources: docs.godotengine.org class_tileset / class_tilesetatlassource / class_tiledata (4.6-pinned), godot 4.6-stable source, forum.godotengine.org/t/121151.

**The built-in terrain solver ships broken in 4.6 AND 4.7; don't build on it.** Issue #76493 (open since 4.0.2): terrain painting picks tiles from entirely wrong terrains even when correct matches exist. Issue #89844: diagonal peering bits are ignored; the rework PR (#108629) is unmerged, so 4.6 ships with it. `set_cells_terrain_connect` also applies only one terrain per call and is credibly slow (perf issue #80635 open; no 4.6 benchmark exists). **4.7 recheck (2026-07-03):** 4.7-stable (2026-06-18) ships all of it unchanged — #76493/#89844/#80635 still open, PR #108629 still unmerged (milestone 4.x, idle since 2026-02-17), and every terrain change that did land in 4.7 is editor-UI only (#119173, #117373, #112349). **Refuted claim to keep out of our code:** "set_cells_terrain_path avoids the diagonal bug" failed verification 0-3; path placement is NOT a workaround.

**The in-house matcher is the autotiling backend (decided 2026-07-03); BetterTerrain demoted to fallback + reference.** Two reasons the presumption flipped. First, a source check: BetterTerrain ignores the engine terrain system entirely and stores its own schema via `set_meta()` on TileSet/TileData, so adopting it couples T1's baked tilesets to an addon-private metadata format while the engine peering bits T2 audits go unread by the runtime. Second, the water-bottom law (below) collapses matching to per-layer binary signatures, so a general solver buys nothing. The matcher lives in the game repo (`systems/worldgen/terrain_matcher.gd`, spec in the sibling plan phase 3): 8-neighbor occupancy signature, exact-match against the T2 audit table, seeded variant pick, loud fallback on miss. BetterTerrain (Unlicense, still maintained) stays as the fallback if the matcher hits a wall; its headless smoke test is no longer a gate and runs only if that fallback is ever actually reached.

**The water-bottom law (design law, 2026-07-03).** Water is the global bottom layer; island edges are always land/water edges; every TileMapLayer autotiles against itself-vs-empty ONLY. Any two materials that must meet visually resolve as a higher layer over a lower one (cliff, path, shore ring included), never as cross-terrain tiles on one layer. Consequences: matcher signatures are 8-neighbor same-layer occupancy masks (256 raw cases collapsing to ~47 canonical blob classes; only the shapes the mask generator can emit are required), one terrain per terrain set (T1 validation rejects more), no cross-terrain audit matrix, no worldgen adjacency constraints for art reasons. Land never reaches a cell border (the landmass mask is a centered eroded rect), so every lookup is cell-local and streaming needs no neighbor-window context. Interior water (ponds, the plains river set) is just holes in the ground layer, same edge logic, free whenever we want it. The edge/corner tiles are biome+water composites with 2-frame water animation (user-confirmed from the packs, 2026-07-03), which settles the water rendering question: in-window water is PAINTED 2-frame animated tiles, not a shader backdrop, because `TILE_ANIMATION_MODE_DEFAULT` starts all tile animations simultaneously (4.7 class docs) and keeps composite-edge water pixels in phase with open water for free. The deep-water backdrop survives only beyond loaded windows, where no composite edge can abut it. Gameplay "is water" = no ground cell = mask bit false.

**Water compatibility + biome water color (grounding + decision, 2026-07-04).** A grounding pass over the local packs (15 of ~100 owned; the rest not yet pulled from itch.io) settled the open water-compatibility question and refined two assumptions in the law above.
- **Pack audit (real pixels sampled):** ForgottenPlains, DesolateDesert, IcyWilderness ship 2-frame water; SilentSwamp ships 4-frame; Plants&Foliage carries separate green/murky/poisonous/fen wetland waters; RTS_Humans has its own animated water. **Water colors: ForgottenPlains, DesolateDesert, AND IcyWilderness all share the same `#4070d0` blue ramp** (Icy's blue water ponds sit at cols 22-28 of its sheet, near the snow/ice ground; a first sample mistakenly grabbed the pale ice `#b8e8f0`/`#e8f8f8` — the actual water is `#4370d0`, a pixel-match). SilentSwamp is the real outlier: 4-frame + murky purple (`#382058`). So the compatible core is **Plains + Desert + Icy** (2-frame, shared blue water, zero recolor needed); only SilentSwamp (both frame count and color) and the Plants&Foliage wetlands (biome-specific colors) fall outside it.
- **Grounding corrections to the law:** the real ForgottenPlains land↔water edge set is a **15-tile CORNER-based (Wang) autotile laid out 3×5** (a 3×3 core plus an inner-corner/connector row), i.e. Godot **MATCH_CORNERS with ~16 classes** (15 land + 1 empty), NOT the ~47 corners+sides the paragraph above assumed. `procgen_terrain_audit` derives the expected count from the set's mode, so it already reports 16 for MATCH_CORNERS with no code change. Water frame count is per-pack, not universally 2. The 3×5 layout is Minifantasy's own, so it needs a `blob15_3x5` / `minifantasy_edges` strategy template (or `explicit`), not the standard `blob47`/`blob16` grids. The two animation frames also sit non-adjacent in the sheet (frame 1 is +4 cols), which needs NO repacking: Godot's `TileSetAtlasSource.set_tile_animation_separation(coords, Vector2i)` sets the grid-tile MARGIN between frames, so the builder places frame N at `base + N*frame_offset` by setting `separation = frame_offset - 1 tile` along the animation axis (e.g. `frame_offset=[4,0]` → `separation=(3,0)`, verified on 4.7: frame 1 region lands exactly at the +4-col cell). Frames stay where the art has them; the atlas grid cells between base and frame 1 are RESERVED (not scanned as standalone tiles).
- **Decisions (2026-07-04):**
  1. **Islands-only world — biomes never meet.** Every landmass is one biome ringed by water, so there are no land-to-land boundaries; the packs' land-to-land transition tiles (grass-on-dirt etc.) are intentionally UNUSED, and the matcher only ever resolves land-vs-water (itself-vs-empty). This closes the layer-vs-cross-terrain question in favor of the law as written, and removes any cross-terrain matrix or biome-adjacency need. Most owned packs are land-designed; under this world they contribute a biome ground + its land-vs-water edges only.
  2. **Water color is hand-authored per biome/pack on import** — chosen over a build-time normalizer OR runtime modulate, for ease and usability. Because islands never touch, each biome's water is independent, so no global-water normalization is required and "which packs are compatible" becomes a non-question: any land pack works once you tint its water on import. **The normalizer/palette-swap tool and the runtime-modulate idea are both dropped.**
  3. **One shared ocean backdrop color** between islands (the only shared water surface); a biome's hand-colored shore water meets that ocean at each island's outer ring, which is an art seam painted by hand, not a system concern.
- **Deferred alternative (NOT chosen):** to recolor only the water pixels of a composite tile ("modulate one bit of a tile") you need a **fragment shader** on the water layer — color-key the water palette (or a baked is-water mask) and remap to a per-biome uniform, leaving land pixels untouched. `modulate`/`self_modulate` tint the whole CanvasItem and cannot do this. Parked; revisit only if hand-authoring per biome gets tedious at scale.
- **Outcome (2026-07-04):** decision applied. **Four biomes are now imported to Godot on a unified `#4070d0` 2-frame blue water:** ForgottenPlains, DesolateDesert, IcyWilderness (compatible as shipped) + SilentSwamp (hand-recolored/reframed to the blue ramp on import). This is the starting **biome roster** for worldgen / `BiomeDef`. **Plants&Foliage is a decor/materials source only** — used for the props and plants it adds, NOT its wetland waters and NOT as a biome. (**Verified 2026-07-04:** water color is unified `#4070d0` across all four biome sheets in `squareds/project1/assets/biomes/`, including the hand-fixed swamp — 6530 canonical-blue px, murky→blue confirmed. **BUT the 2-frame animation is NOT yet configured:** the only built tileset, `plains/plainstileset.tres`, has zero animated tiles, and desert/ice/swamp have no `.tres` yet (imported PNGs only). The 2-frame water is applied when the biome tilesets are built through `procgen_tileset_build` with its `[[animation]]` config — the hand-built plains tileset skipped it.)

**Biome region painting needs no addon.** Built-in FastNoiseLite `TYPE_CELLULAR` with `cellular_return_type = RETURN_CELL_VALUE` plus built-in domain warping (`domain_warp_enabled`) produces organic contiguous same-value regions. Empirically verified headless on THIS machine's 4.6.2: a 15x15 sample yielded 9 unfragmented contiguous regions (flood-fill checked). Defaults without cell-value return are unusable (distance field). This is exactly the worldgen §2 region painter: cell value → biome index, warp for natural coastal wobble, plus our constraint pass (center plains, band weighting, reachability).

**Skip the procgen addons.** Gaea 2.0 self-describes as early development with possible breaking changes every update, no stable 2.0 tag (v1.4.1, 2025-04) and a maintainer warning about larger projects; its exact engine-version targeting is unsettled (one claim refuted 1-2), so re-check the repo only if we ever reconsider. The WFC addon (godot-constraint-solving) is well-designed (infers rules from sample maps, TileMapLayer support, works in running games which fits headless SceneTree tooling) but stale since Oct 2024 with untested 4.6 compat; park it as a possible later experiment for chunk-template variety, never a dependency. infinite_worlds is abandoned (feature-frozen, last real commit Nov 2023). Build on engine primitives.

**Preview rendering: strong lead, not verified.** Research area 5 produced zero claims that survived verification. The search-phase lead (proposal #5790: `--headless` uses a dummy rasterizer, all rendering disabled, so captures need a real window/GPU) is credible but unconfirmed. The preview architecture does not gamble on it either way: **previews are composed in Python** (PIL) from worldgen data + the source PNGs, no engine rendering involved. If true in-engine screenshots are ever wanted, run the cheap local experiment first (spike S3).

**Unverified areas (need local experiments, not web claims):** large-TileMapLayer perf/chunking best practices produced zero confirmed claims. Our streaming design (3x3 window of 96x96-tile cells, deep water as backdrop) keeps active cell counts small, so this is a P0 probe, not a blocker. Knobs the probe should exercise: `rendering_quadrant_size` (default 16; ignored on y-sorted layers, which group by Y instead, relevant to our y-sorted props layer) and `physics_quadrant_size`.

## 2. The tools to build (ranked)

**Tool naming (decided 2026-07-03).** The suite registers under a new **`procgen_*`** family, joining the naming families settled in Phase 6.6 (`godot_*` engine grounding + validate/edit/test, `project_*` project grounding, `editor_*` live editor bridge). `procgen_` is the accurate umbrella — it covers both the tileset-construction tools (T1/T2/T5) and the generation-preview tools (T3/T4/T6); `worldgen_*` was rejected because it mischaracterizes tileset building. The bare tool names used throughout this doc and the sibling plan are shorthand for their registered `procgen_`-prefixed form:

| shorthand (used below) | registered name |
|---|---|
| `tileset_build` | `procgen_tileset_build` |
| `terrain_audit` | `procgen_terrain_audit` |
| `worldgen_preview` | `procgen_worldgen_preview` |
| `island_preview` | `procgen_island_preview` |
| `chunk_lint` | `procgen_chunk_lint` |
| `gen_smoke` | `procgen_gen_smoke` |

(`procgen_worldgen_preview` / `procgen_gen_smoke` read slightly redundant; Phase 0 may tighten those two nouns — e.g. `procgen_world_preview` / `procgen_smoke` — but the `procgen_` family prefix is locked.)

| # | Tool | What it does | Grounding |
|---|---|---|---|
| T1 | `tileset_build(pack_config)` | Generate a `.tres` TileSet from a declarative per-pack config (atlas sources, sheet scan honoring transparent cells, terrain sets + peering bits, physics/nav polygons, custom-data layers for biome metadata). Bakes tile animation (frames/columns/separation/duration; mode locked to DEFAULT for water-bearing tiles); the sheet scanner is animation-aware (frame regions consume real atlas grid space and are reserved, never registered as tiles); bakes per-signature-class collision polygon templates on edge tiles; validation enforces one terrain per terrain set (the law). Runs a headless Godot script, parse-checked like the mcp's existing write tools. | fully verified, build first |
| T2 | `terrain_audit(tileset)` | Report per terrain: signature coverage against the fixed itself-vs-empty checklist (~47 blob classes, computed from the set's mode), missing/duplicate signatures (duplicates = variants, allowed — the matcher's seeded pick uses them), dead tiles, mode mismatches, plus the animation sync lint (every water-bearing tile shares identical frame count/duration/mode; mode must be DEFAULT). This is our QA for T1 output AND the dataset the matcher consumes. | verified APIs; motivated by solver bugs |
| T3 | `worldgen_preview(world_seed)` | Run WorldGen headless (region paint + archetypes + dungeon placement), emit the 15x15 biome map as PNG (PIL, color per biome, markers for hub/dungeons) + ascii fallback in the tool result. | FastNoiseLite path empirically verified; PIL sidesteps the headless-render wall |
| T4 | `island_preview(tile_coords, world_seed)` | Materialize one tile headless, dump cell data (layer, atlas coords per cell), compose a PNG in Python by stamping 8px tiles from the source atlas PNGs. Faithful pixel preview without engine rendering; animated tiles stamp frame 0 consistently. | same architecture as T3 |
| T5 | `chunk_lint(template)` | Validate ChunkTemplates: expected layer names, size bounds, terrain ids exist in the tileset, no out-of-palette tiles, stamp-safety (no dangling scene refs). | pure data validation; no engine risk |
| T6 | `gen_smoke(world_seed)` | Determinism + budget check: worldgen twice → identical TileRecords; materialize a sample tile twice → identical cell hashes; report timing against the sub-second target. | protects the save-stores-seeds contract |

T1+T2 unblock the minifantasy import pipeline (ART_PIPELINE choose-pass). T3 makes the worldgen loop reviewable in chat before any game UI exists. T4-T6 land with the generator itself.

## 3. Spikes before design lock

- **S1: matcher + audit spike on the real plains tileset (reframed 2026-07-03; was the BetterTerrain smoke test).** Bake the plains TileSet with T1, run T2, then a throwaway headless script resolves a toy landmass mask via the audit table: assert interior/straight-edge/inner-corner/outer-corner picks, hand-check the coastline render, time a 96x96 solve. Green → record under an "S1 verdict" heading here; the game repo implements `terrain_matcher.gd` per spec. Only if this fails does the parked BetterTerrain smoke test run.
- **S2: streaming perf probe (P0).** Worst-case cell materialization + border-crossing hitch measurement at 96x96 cells, y-sort on, both quadrant-size knobs swept. No verified web guidance exists; measure, don't believe forums.
- **S3: windowed capture (optional, later).** Only if PIL previews prove insufficient for review needs.

## 4. Watch items

- PR #108629 (diagonal terrain rework): **RESOLVED 2026-07-03 — stop watching.** 4.7-stable shipped without it (still open, milestone 4.x, idle since 2026-02-17). Custom-build option assessed and rejected the same day: the cherry-pick is easy (2 files, applies near-clean, this machine builds Godot comfortably) but the patch is unreviewed with author-flagged regressions, fixes only the diagonal class (perf #80635 and one-terrain-per-call untouched), and a runtime dependency means shipping a forked engine. Under the matcher architecture the engine solver is irrelevant to us; an eventual upstream merge would improve editor hand-painting only (ChunkTemplates are authored with explicit tiles, so nothing blocks).
- Gaea 2.0 stabilizing or the WFC addon releasing again: re-evaluate only for chunk-template variety, not for core worldgen.

## S1 verdict

**S1 PASSES (2026-07-04, live against Godot 4.6.2-stable on this machine).** The in-house matcher resolves every reachable land-vs-water shape correctly for the mode the game ships (MATCH_CORNERS), well inside the materialize budget. The game repo may implement `systems/worldgen/terrain_matcher.gd` by porting the signature helper below verbatim. Only if a real-art failure the audit cannot explain shows up later does the parked BetterTerrain fallback get evaluated.

**Adjustment from the plan text.** Per the 2026-07-04 grounding correction, this spike validated **MATCH_CORNERS** (the shipping mode), not the ~47 corners+sides the older law assumed, and used a **synthetic full-coverage sheet** (built through the real `procgen_tileset_build`), not the ForgottenPlains art — the real-art config is a later, separate step. The eyeball pass therefore checks coastline SHAPE coherence, not real-art fidelity.

**Grounding finding (blocker filed for a later procgen module phase — not fixed here, the spike does not edit the module).** Square-grid **MATCH_CORNERS uses the four DIAGONAL corner peering bits** (`TOP_RIGHT_CORNER`, `BOTTOM_RIGHT_CORNER`, `BOTTOM_LEFT_CORNER`, `TOP_LEFT_CORNER`), verified live via `TileData.is_valid_terrain_peering_bit` on 4.6.2. But `procgen.blob16_corners_table` and `expected_signature_set("MATCH_CORNERS")` currently emit the **axis-aligned CORNER bits** (`TOP_CORNER`/`RIGHT_CORNER`/`BOTTOM_CORNER`/`LEFT_CORNER`), which are hexagonal/isometric-grid bits the engine REJECTS on a square grid. Consequence: a sheet built with `strategy = "blob16_corners"` audits as **all-isolated (0 of 16 covered)** — the peering bits are silently dropped at build time. The spike therefore authored its synthetic sheet with `strategy = "explicit"` supplying the correct diagonal-corner bits (which is the real shipping shape anyway — the design doc already flags the real ForgottenPlains edges need an `explicit`/`minifantasy_edges` layout, not the standard `blob16` grid). **Fix owed in a later module phase:** correct `blob16_corners_table` (and the MATCH_CORNERS branch of `expected_signature_set`) to the diagonal-corner bits + the Wang-corner rule below, and re-point its unit tests. The matcher spec is now committed offline as `tests/test_terrain_matcher_spec.py` (the correct diagonal-corner derivation), so the fix has a target to match.

**Timings.** Full 96×96 resolve (7552 ground cells, eroded rect + bay + ponds): **17.9 ms** in plain Python, no per-cell allocation beyond the signature string. Budget is the game plan's 150 ms materialize target — the resolve is ~12% of it, with the GDScript port expected in the same order (the #80635 thread's plain-GDScript numbers suggested large headroom, confirmed).

**Hand-computed assertions (all PASS).** Toy 20×20 landmass (centered eroded rect, an L-notch bay on the right, an interior 2×2 pond). Each cell's correct MATCH_CORNERS signature was computed by hand and the matcher's pick asserted to carry exactly that signature:

| category | cell (x,y) | expected signature | result |
|---|---|---|---|
| interior | (3,16) | `BOTTOM_LEFT_CORNER,BOTTOM_RIGHT_CORNER,TOP_LEFT_CORNER,TOP_RIGHT_CORNER` | PASS (picked atlas (3,3)) |
| straight-edge (top) | (8,2) | `BOTTOM_LEFT_CORNER,BOTTOM_RIGHT_CORNER` | PASS (picked atlas (2,1)) |
| straight-edge (left) | (2,10) | `BOTTOM_RIGHT_CORNER,TOP_RIGHT_CORNER` | PASS (picked atlas (3,0)) |
| outer-corner (convex island tip) | (2,2) | `BOTTOM_RIGHT_CORNER` | PASS (picked atlas (2,0)) |
| inner-corner (concave, pond SE) | (7,7) | `BOTTOM_LEFT_CORNER,BOTTOM_RIGHT_CORNER,TOP_RIGHT_CORNER` | PASS (picked atlas (3,1)) |

Coverage of the synthetic sheet: all **16 diagonal-corner classes covered, 0 missing**, `procgen_terrain_audit` reported CLEAN. Matcher misses across both the toy and 96×96 resolves: **0** (every shape exact-matched; the full-interior fallback was never taken). Note the inner-corner/outer-corner distinction is only meaningful under the *diagonal-corner* MATCH_CORNERS rule; under the module's current (buggy) axis-aligned rule the concave pond corners collapse to full-interior and the distinction vanishes — a second reason the blob16_corners fix matters.

**Eyeball render.** `test-results/s1/s1_island.png` (synthetic art, animated water at frame 0, x8 nearest-neighbor). Coastline shape is coherent: the four island corners are distinct convex-corner tiles, each straight edge uses one consistent edge tile per orientation, the interior pond is cleanly ringed by four concave inner-corner tiles + straight edges, and the L-notch bay shows the correct concave corners where its walls meet the land.

**Port-ready matcher core (the game copies this signature derivation into GDScript).** Under the water-bottom law the mask is same-layer land-vs-empty; off-mask cells are water (land never reaches a border). A diagonal corner bit is set iff the diagonal neighbor and BOTH cardinals flanking it are ground (Wang-corner rule). The key format matches what `procgen_terrain_audit` emits (set corner-bit names, sorted, comma-joined; `""` = isolated), so the matcher looks its own key up directly in the audit `coverage[set]["signatures"]` table:

```python
_CORNER_RULE = {
    "TOP_RIGHT_CORNER":    ("N", "NE", "E"),
    "BOTTOM_RIGHT_CORNER": ("S", "SE", "E"),
    "BOTTOM_LEFT_CORNER":  ("S", "SW", "W"),
    "TOP_LEFT_CORNER":     ("N", "NW", "W"),
}
_NEIGHBOR_OFFSETS = {
    "N": (0, -1), "E": (1, 0), "S": (0, 1), "W": (-1, 0),
    "NE": (1, -1), "SE": (1, 1), "SW": (-1, 1), "NW": (-1, -1),
}

def corner_signature_key(mask, x, y):
    """MATCH_CORNERS diagonal-corner signature key for the ground cell (x, y).
    mask(x, y) -> bool is True iff that cell is ground (same layer); off-mask is
    water. Returns the sorted, comma-joined set corner-bit names ("" = isolated).
    """
    bits = []
    for bit_name, (a, d, b) in _CORNER_RULE.items():
        ax, ay = _NEIGHBOR_OFFSETS[a]
        dx, dy = _NEIGHBOR_OFFSETS[d]
        bx, by = _NEIGHBOR_OFFSETS[b]
        if mask(x + ax, y + ay) and mask(x + dx, y + dy) and mask(x + bx, y + by):
            bits.append(bit_name)
    return ",".join(sorted(bits))
```

Resolve wrapper (also ported): exact-match `corner_signature_key` in `coverage[set]["signatures"]`; among variant tiles for a key, a seeded position-stable **WEIGHTED** pick (below) tie-broken by `(source_id, atlas_x, atlas_y)` order; on a miss, fall back to the full-interior tile (`BOTTOM_LEFT_CORNER,BOTTOM_RIGHT_CORNER,TOP_LEFT_CORNER,TOP_RIGHT_CORNER`) and emit a loud debug line. On a full sheet the fallback is never reached (0 misses here).

**Per-variant weighting (added 2026-07-06).** Each tile dict in `coverage[set]["signatures"]` now carries a `weight` float (relative, positive; default `1.0` for unweighted builds — see `procgen_terrain_audit`'s coverage-dict contract). The variant pick is a DETERMINISTIC WEIGHTED roll: a variant's probability is proportional to its weight, so a biome interior can be mostly one tile (plain grass `0.9`) with rare variants (tufts `0.05` each). Weights are RELATIVE — `[0.9, 0.05, 0.05]` and `[18, 1, 1]` behave identically (normalized at pick time). Equal weights reduce EXACTLY to the prior uniform pick (`int(u * n)` over the sorted variants), so unweighted sheets are unaffected. The weight flows config (`interior` entry `[col, row, weight]`) → the tile's `weight` custom-data layer in the `.tres` → the audit `coverage` dict → this pick. The game ports this verbatim alongside `corner_signature_key`:

```python
_U32 = 0xFFFFFFFF

def _cell_hash01(seed, x, y):
    """Deterministic pseudo-random value in [0, 1) for a cell (FNV-1a-style
    32-bit mix; pure integer ops so a GDScript port is bit-identical — Godot
    ints are 64-bit, the & _U32 masks keep every step inside 32 bits)."""
    h = 2166136261
    for v in (seed, x & _U32, y & _U32):
        h ^= v & _U32
        h = (h * 16777619) & _U32
        h ^= (h >> 15)
        h = (h * 2246822519) & _U32
    h ^= (h >> 13)
    h &= _U32
    return h / 4294967296.0

def pick_variant(variants, x, y, seed):
    """Pick one variant tile for cell (x, y) by a deterministic WEIGHTED roll.
    `variants` is coverage[set]["signatures"][key]; each dict has source_id,
    coords [ax, ay], and weight (default 1.0). Same (variants, x, y, seed) ->
    same tile; chance ∝ weight_i / sum(weight); equal weights -> uniform."""
    ordered = sorted(variants, key=lambda t: (t["source_id"], t["coords"][0], t["coords"][1]))
    weights = [float(t.get("weight", 1.0)) for t in ordered]
    total = sum(weights)
    u = _cell_hash01(seed, x, y)
    target = u * total
    cumulative = 0.0
    for tile, w in zip(ordered, weights):
        cumulative += w
        if target < cumulative:
            return tile
    return ordered[-1]
```

This unblocks the game plan's phase 3 (`terrain_matcher.gd`), with one carry-in: the game's tileset build must supply the diagonal-corner bits (via `explicit`/`minifantasy_edges`), not the current `blob16_corners` strategy, until that module bug is fixed.
