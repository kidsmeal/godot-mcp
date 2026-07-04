# Research Record: Godot 4.6 Tilemap/Tileset Tooling for Procedural Biome Islands

**Run 2026-07-02** via the deep-research harness: 5 search angles, 23 sources fetched, 114 claims extracted, 25 adversarially verified (3 skeptical voters per claim, 2/3 refutations kill), 23 confirmed, 2 refuted, 7 dropped on budget, 11 findings after synthesis, 105 agent calls. This file is the complete compiled record; the decision distillation lives in `../design/procgen-tools.md`, the consuming plans in `../design/procgen-tools.plan.md` (this repo) and the game repo's `docs/plan_island_generation.md` (`C:\Users\atk67\Documents\squareds\project1`). All statuses are snapshots of 2026-07-02.

Research question, condensed: can an in-house Python FastMCP server driving headless Godot 4.6 automate (1) programmatic TileSet creation, (2) runtime terrain autotiling, (3) natural biome-region generation, (4) large seamless TileMapLayer worlds, (5) map preview rendering, and which MCP tools should exist.

## Confirmed findings (survived 3-vote adversarial verification)

### F1. Headless tileset building is fully feasible (HIGH, 3-0)
TileSet is a plain Resource (a library of TileSetSource objects); TileSetAtlasSource builds tiles from a spritesheet. Tiles are not auto-derived: the builder must iterate the sheet and call `create_tile(atlas_coords, size)` per tile (`remove_tile` / `move_tile_in_atlas` for edits), then configure per-tile properties through TileData objects from `get_tile_data(atlas_coords, alternative_tile)`, main tile at alternative 0. TileSetAtlasSource itself exposes no terrain/physics/navigation API (that is all TileData). The editor's "Create Tiles in Non-Transparent Texture Regions" convenience has no script API. Nuance: TileData serializes as pseudo-properties on the atlas source in `.tres` text (e.g. `0:0/0/terrain_set`), so direct `.tres` writing bypasses the API path.
Sources: class_tilesetatlassource (stable + 4.6-pinned), class_tileset, forum thread 121151.

### F2. Terrain sets and peering bits fully scriptable, no editor step (HIGH, 3-0)
`TileSet.add_terrain_set()`, `set_terrain_set_mode()` (three modes; default TERRAIN_MODE_MATCH_CORNERS_AND_SIDES, confirmed in 4.6-stable engine source `scene/resources/2d/tile_set.h`), `add_terrain()`, `set_terrain_name()/set_terrain_color()`; per tile `TileData.terrain_set` and `terrain` (both default -1), `set_terrain_peering_bit(bit, terrain)`, `is_valid_terrain_peering_bit()`. **Ordering constraint: terrain_set must be assigned before terrain/peering bits**, and bit validity depends on the set's mode. TileData is runtime-modifiable.
Sources: class_tileset, class_tiledata (stable + 4.6), 4.6-stable TileSet.xml.

### F3. Physics/nav/occlusion/custom-data layers scriptable end to end (HIGH, 3-0)
`add_physics_layer()` + collision layer/mask/priority/material setters, `add_navigation_layer()` + `set_navigation_layer_layers()`, `add_occlusion_layer()`, `add_custom_data_layer()` + name/type setters; per tile `TileData.add_collision_polygon(layer_id)`, `set_collision_polygon_points()`, one-way flags/margins, `set_constant_linear_velocity()`, `set_navigation_polygon()`, `set_custom_data`. Pure data ops on a Resource, no RenderingServer dependency; `ResourceSaver` works under `--headless`. **Version gotcha:** `set_physics_layer_collision_priority` exists only from 4.4 (issue #98772 / PR #98773).
Sources: class_tileset, class_tiledata (4.6), issue #98772.

### F4. The built-in terrain solver ships broken in 4.6 (HIGH, 3-0 on all 4 merged claims)
(a) **#76493** (filed 4.0.2, still open, zero maintainer repro on-thread but triage-labeled and sibling-corroborated by #73903, #114407 (TileMapLayer era, Dec 2025), and proposal #7670, where the Terrain Autotiler author analyzes the engine solver as a local solver with small scope, linear update order, no backtracking): terrain painting selects tiles from completely different terrains even when correct matches exist and all tiles are fully bitmasked; results are non-deterministic relative to bitmasks (depend on terrain order, selected paint tile, paint order). Verbatim: "incorrect tiles are selected even though there are correct matches in the tileset."
(b) **#89844** (open, 26 comments): in Match Corners and Sides mode, `set_cells_terrain_connect()` ignores diagonal (corner) peering bits; reproduced 4.2.1/4.3-dev5, confirmed 4.4.1 (2025-04-26). The fix PR **#108629** ("Fix diagonal tiling and remove ambiguity from terrain constraints", July 2025) is open, merged=false, milestone bumped 4.5 → 4.6 → 4.x, last updated 2026-02-17. Godot 4.6 stable shipped 2026-01-26 without it. Scope caveat: the diagonal bug specifically affects terrains using corner bits in corners-and-sides mode. A terrain-audit tool should flag terrain sets relying on diagonal bits.
Sources: #76493, #89844, PR #108629, proposal #7670.

### F5. No whole-map multi-terrain reapply exists in Godot 4 (HIGH, 3-0)
A regression from Godot 3's `update_bitmask_region`: 4.6 TileMapLayer exposes exactly two terrain methods, `set_cells_terrain_connect(cells, terrain_set, terrain, ignore_empty_terrains)` and `set_cells_terrain_path(...)`, each taking ONE terrain per call. A multi-biome generator on the built-in API must issue one call per terrain; BetterTerrain's `update_terrain_area` or manual `set_cell` selection are the outside options. Verbatim from #76493: "you can currently only apply one terrain at a time programmatically."
Sources: #76493, class_tilemaplayer (4.6), #66981.

### F6. Built-in solver performance is credibly bad; no evidence 4.4-4.6 improved it (HIGH, 3-0)
BetterTerrain's stated reason to exist: "It's also quite slow, and the API is difficult to use at runtime" (author assessment, 4.0-4.x era). Corroborated by still-open **#80635** ("Tilemap autotiling too slow to be updated every frame", Aug 2023: ~50 FPS via set_cells_terrain_connect vs 1000+ FPS custom GDScript) and **#69927** (batched set_cells_terrain_connect on 50x50 took 2.861s vs 0.147s per-cell; partial fix PR #69950). For ~2M cells this is an architecture risk. A 4.6 re-benchmark is prescribed before locking the backend; none surfaced.
Sources: better-terrain README, #80635, #69927.

### F7. BetterTerrain is the stronger runtime autotiling option for 4.6-era scripted worldgen (HIGH, 3-0)
Verified at code level on main: `addons/better-terrain/BetterTerrain.gd` defines `func set_cells(tm: TileMapLayer, coords: Array, type: int) -> bool` and `func update_terrain_cells(tm: TileMapLayer, cells: Array, and_surrounding_cells := true)` plus `update_terrain_cell` and `update_terrain_area`; `TerrainPlugin.gd` registers the `BetterTerrain` autoload; doc comments state `set_cells` does not run the solver and `update_terrain_*` must be called. **Two-phase set-then-solve** gives a generator exact control over which cells re-solve, which the built-in single-call API cannot do. Alive and license-clean: pushed 2026-02-09, asset-store update 2026-06-23 (min Godot 4.3), 736 stars, Unlicense (public domain), not archived, README/API written against TileMapLayer, no 4.6 breakage reports found. **Headless and exported-game behavior is undocumented; smoke test required before MCP adoption** (it registers an editor-plugin autoload).
Sources: better-terrain repo + GitHub API, asset-library listing.

### F8. Biome region painting needs no addon; empirically verified on this machine (HIGH, 3-0)
FastNoiseLite is built-in (Noise < Resource < RefCounted < Object; Cellular/Perlin/Value and more; headless-usable). TYPE_CELLULAR implements Worley/Voronoi: "creates various regions of the same value". Domain warping is built in (`domain_warp_enabled` uses a second internal FastNoiseLite; amplitude default 30.0, frequency default 0.05, independent fractal settings) to make Voronoi borders organic. **Empirical run on the user's own godot v4.6.2.stable.official via `godot --headless -s`:** `cellular_return_type=RETURN_CELL_VALUE`, frequency 0.12, 15x15 grid → 9 distinct values, every one a single 4-connected contiguous blob (flood-fill checked). **Critical config: the defaults (RETURN_DISTANCE, frequency 0.01) do NOT produce regions** (225 distinct values, a distance field). Scale frequency to the grid, ~0.1-0.15 for 15x15.
Sources: class_fastnoiselite, godot modules/noise, local empirical test.

### F9. Gaea: do not adopt now (MEDIUM, 3-0; sibling claim refuted)
Gaea 2.0 (graph-based rewrite, "similar to VisualShaders") is self-described early development, "may not yet be optimized for larger, more complex projects", breaking changes possible every update, no stable 2.0 tag (latest v1.4.1, 2025-04-13). Graded medium: single-repo source (though authoritative for its own warning). **The related claim that Gaea's 2.0 line requires Godot 4.4 with no 4.6 support was REFUTED 1-2: check the repo directly before any future adoption call.**
Source: gaea repo.

### F10. WFC addon (godot-constraint-solving): well-shaped, stale, park it (HIGH, 3-0)
Targets TileMapLayer and TileMap plus flat GridMap planes; infers WFC rules from an example sample map (optional negative samples) rather than hand-authored constraints; rule learning works only in a running game, not the editor, which actually fits headless SceneTree tooling (`start_on_ready` off, call `start()` manually). v1.7 (2024-10-04, latest of exactly 9 releases) added rule inference from tileset terrain settings for square tilemaps (matches this project). TileMapLayer support arrived in 1.6 (Aug 2024, Godot 4.3 features). Only later activity: one "import to godot 4.4" commit (May 2025). 4.6 compat untested by the maintainer; zero breakage reports; pure GDScript on stable 4.3+ APIs. Asset library still lists 1.7 / Godot 4.3.
Sources: repo, releases API, asset-library 1951.

### F11. Chunked-streaming research came back empty; infinite_worlds is dead (MEDIUM, 3-0)
The only surviving area-4 claim is negative: infinite_worlds is feature-frozen by its author ("I will not add any new features"), 11 commits all 2023, last real commit "updated godot to 4.2" (Nov 2023), self-described work-in-progress demo "not production ready, there are many bugs", no maintained fork or asset-library successor. **No claims about 1440x1440 TileMapLayer performance limits, quadrant/rendering settings, or chunking best practices survived verification.** Chunk-lint and streaming designs currently have no verified web grounding; measure locally.
Sources: infinite_worlds repo + commit history.

## Refuted claims (must not leak into designs)

1. **"set_cells_terrain_path is unaffected by the diagonal bug and is a viable workaround"** — killed 0-3 (#89844). Do not build path-based placement as a bug dodge.
2. **"Gaea 2.0 requires Godot 4.4, no 4.6 support documented"** — killed 1-2. Gaea's engine targeting is unsettled; re-check the repo before any adoption discussion.

## Unverified leads (search-phase material that never reached the verify stage; treat as pointers, not facts)

- **Headless rendering (area 5, zero verified claims):** proposal #5790 (off-screen rendering) states `--headless` uses a dummy rasterizer with all rendering code disabled, so screenshots/Movie Maker require a real window; related: creating_movies.html docs, issue #106957, viewports tutorial. This motivated (but does not verify) the decision to compose previews in Python/PIL from dumped data, which is robust regardless of the truth here. A cheap local experiment can settle it if in-engine capture is ever wanted (tooling plan spike S3).
- **Perf knobs (area 4):** TileMapLayer docs list `rendering_quadrant_size` (default 16, i.e. 256 tiles per canvas item; **ignored on Y-sorted layers, which group by Y instead**) and `physics_quadrant_size`; forum thread 53518 and issue #72458 discuss chunking pain. All unverified; the P0 streaming probe (spike S2) owns this.

## Open questions the research could not close

1. Can headless Godot 4.6 capture SubViewport textures at all, or does the preview path require a hidden-window GPU run or movie mode? (Decides nothing critical now; PIL previews sidestep it.)
2. Actual cost of a seamless 1440x1440 TileMapLayer (~2.07M cells, 8px tiles): load, memory, rendering, and where layer-splitting or streaming becomes mandatory. (Our design streams 3x3 windows of 96x96 cells regardless; probe at P0.)
3. Does BetterTerrain run correctly under `--headless` SceneTree scripts, and what is its solve throughput on large areas vs the built-in (#80635 suggests built-in is unchanged; neither side has a 4.6 benchmark)? (Spike S1, gates the backend choice.)
4. Will PR #108629 merge for 4.7, and would it change the terrain-audit rules or the backend decision? (Watch item.)

## Source table (23 fetched)

| Source | Quality | Angle |
|---|---|---|
| docs.godotengine.org class_tilesetatlassource | primary | tileset build |
| docs.godotengine.org class_tiledata | primary | tileset build |
| docs.godotengine.org class_tileset | primary | tileset build |
| godot-proposals discussion 8664 | forum | tileset build |
| github Portponky/better-terrain | primary | autotiling/BetterTerrain |
| godot issue #76493 | primary | autotiling |
| forum: lag with set_cells_terrain_connect (73345) | forum | autotiling |
| godot issue #89844 | primary | autotiling |
| forum: terrain_connect not working (46877) | forum | autotiling |
| godot issue #75317 | forum | autotiling |
| github gaea-godot/gaea | primary | addon landscape |
| github AlexeyBond/godot-constraint-solving | primary | addon landscape |
| redblobgames terrain-from-noise | blog | addon landscape |
| docs.godotengine.org class_fastnoiselite | primary | addon landscape |
| github Lommix/infinite_worlds | primary | addon landscape |
| godot asset-library 3272 | primary | addon landscape |
| docs.godotengine.org class_tilemaplayer (latest) | primary | perf/chunking |
| godot issue #72458 | primary | perf/chunking |
| forum: tilemap chunkloading efficiency (53518) | forum | perf/chunking |
| godot-proposals issue #5790 | primary | headless preview |
| docs: creating_movies tutorial | primary | headless preview |
| godot issue #106957 | primary | headless preview |
| docs: viewports tutorial | primary | headless preview |

Additional sources cited inside findings: godot 4.6-stable source (tile_set.h, TileSet.xml), issues #98772/#73903/#114407/#66981/#69927, PRs #108629/#98773/#69950, proposal #7670, better-terrain GitHub API + asset listing, constraint-solving releases API + asset 1951, forum 121151, local empirical FastNoiseLite test on godot 4.6.2.

## Method notes

Claims were extracted from fetched sources as falsifiable statements, then each surviving claim faced three independent adversarial verifiers instructed to refute (2/3 refutations kill). 23 of 25 confirmed, 2 killed, 0 left unverified in the verified set; 7 extracted claims were dropped on budget before verification (they are not represented here beyond the unverified-leads section). The single strongest piece of evidence in the record is the local empirical FastNoiseLite run on this machine's own binary; the weakest confirmed finding is Gaea (single-source, medium). Raw run output lived in the session temp dir and is not durable; this file is the durable record.
