# Biome-world (procgen v3) — tools scope

Status: reviewed + resolved 2026-07-06. Ready for phase planning HERE on the
TOOLS deltas (§3). The GAME-repo work (§4) is being reconciled separately in
`squareds/project1` against its existing world design (`design/world_and_biomes.md`),
so do NOT plan §4 here.
Forks: `procgen-tools.md` v2 (water-bottom law, islands-only).
Reviewed against the generic design-quality checklist (no project rubric exists);
reuse claims verified against `src/godot_mcp/procgen.py`.

## 1. Why

v2 is islands-only: water is the global bottom, each biome is its own island,
land autotiles vs water/empty. v3 is one contiguous all-land world where biomes
are blob regions that meet directly and blend through transparent-edge transition
art. Exploration is gated by a hex unlock/fog overlay, not by water. The
corner-Wang engine survives; the *law* forks and a worldgen front-end is added.

## 2. The design the tools serve (shared context)

- **Two decoupled maps.** A biome map (continuous square-tile terrain) and a hex
  map (unlock/fog overlay) that never reference each other. A streamer bridges them
  (listens for hex unlocks, calls the hex-agnostic region baker with a plain rect).
- **Roster + priority:** `desert > ice > swamp > plains`, highest to lowest, water
  (lakes) as the base below. Higher priority spills its edge outward onto the lower
  neighbor; plains grass is the base canvas the others feather onto.
- **Biome-layer law** (replaces the water-bottom law): base biome fill, then for a
  cell of biome X draw each higher-priority neighbor biome Y's transition block,
  shaped by the corner-Wang matcher over "is neighbor == Y", stacked ascending so
  the highest present wins on top. Multi-biome junctions resolve per corner (Y
  lights a corner only when the diagonal + both flanking cardinals are all Y;
  mixed corners fall back to base). No special-case junction logic.
- **Two edge mechanisms:** land↔land seams use the transparent transition panels;
  land↔lake shores use the v2 `minifantasy_edges` land/water coastline block.
  Water is one unified blue, so lakes are consistent and need no per-biome-pair
  edges. Draw order: base fill → coastline pass → land-land panel pass.
- **Footprint reuse:** the transition panels are the same 3x5 corner-Wang block as
  v2 `minifantasy_edges`, with the "outside" transparent (lower biome shows
  through) instead of water. Verified in code (§5).

### 2.1 The biome field (cemented 2026-07-08)

How a cell's biome id is chosen. Every step is a pure function of `(seed, x, y)`,
so the field stays per-region computable, deterministic, and seam-matching.

1. **Voronoi blob regions, domain-warped.** Seed points sit on a hash-jittered
   lattice; the spacing (`region_size`) sets biome-region size. Each cell takes the
   biome of its nearest seed. Before that lookup, the sample coordinate is displaced
   by **smooth (value) noise** — the domain warp.

   **The warp is not optional.** Without it, Voronoi cells meet along straight
   polygon edges, and 3 CA passes only soften ~3 tiles of a ~140-tile region, so
   boundaries render as long straight lines. The warp is what makes them wander.
   White per-cell hash noise cannot do this; the warp needs interpolated value noise.

   Nearest-seed scans the 3x3 lattice neighbourhood around the WARPED coordinate, so
   init needs no neighbour grid and stays O(1) per cell. This is the painter v2
   already verified headless (FastNoiseLite `TYPE_CELLULAR` + `RETURN_CELL_VALUE` +
   domain warp); the Python tool reimplements its *shape*, not its code.

   - **Scale.** Biome regions are HEX-SCALE, not tens of tiles: `region_size` ~140
     tiles, roughly one hex across. `world_and_biomes.md`'s "organic blobs of roughly
     8-20 tiles" counted ISLAND CELLS, each 96 art tiles wide — it never meant 14 art
     tiles. A `region_size` in the low tens renders the world as biome speckle: a new
     biome every few steps of the 40-tile viewport.
   - **Constraint.** `jitter <= region_size / 2`, or a seed escapes its own lattice
     cell and the 3x3 scan can miss the true nearest seed, silently degrading the
     Voronoi. Validate it rather than trusting the caller.

2. **Radial harshness weighting — applied to the SEED, never the cell.** Each biome
   carries a `harshness` in [0,1] (defaults, tunable: plains 0.0 gentlest, swamp
   0.45, desert 0.7, ice 1.0 harshest). A seed at normalized radius
   `t = clamp(r / world_radius, 0, 1)` draws its biome from a weighted pick,
   `weight_i = exp(-(h_i - t)^2 / (2*sigma^2))`, using that seed's own hash. Gentler
   biomes therefore dominate near the centre and harsher ones far out —
   statistically.

   **This is what prevents concentric rings.** Radius biases a random DRAW; it never
   maps to a biome. Two seeds at the same radius can land on different biomes, so no
   band can form. `sigma` is the mixing knob (larger = more blending, less banding).
   **Never reintroduce a radius -> biome mapping.** An earlier phase-4 draft did
   exactly that (distance bands cycling the biome list) and produced a bullseye
   ripple that repeated desert->ice->swamp->plains outward forever.

3. **Cellular-automata smoothing.** 3 passes of Moore-neighbourhood majority vote,
   ties broken by lowest biome index, organicizing the Voronoi edges.

4. **Plains core, stamped last.** The world has a real centre (the hub, the start),
   so a hard disc of plains at world origin guarantees every new game begins in an
   all-plains start hex.
   - `core_hard_radius` >= the start hex's circumradius + margin. For the ~140-tile
     flat-to-flat hex of §4, circumradius = 140/sqrt(3) ~= 81 tiles, so ~88 with
     margin. Nothing overrides this disc; it is stamped AFTER the CA passes, or
     smoothing would erode the guarantee.
   - A hash-jittered blend band beyond it lets plains bleed outward on an organic
     boundary (applied BEFORE the CA passes, so smoothing softens it), so the core
     never reads as a stamped circle.

**The core is a disc, not a hex.** The biome map still knows nothing about the hex
grid — it knows about a *centre*. The game places the start hex at the origin, and
the disc is sized so whatever hex lands there is entirely plains. The only coupling
is that one radius constant, documented here.

### 2.2 World scale (canonical, 2026-07-08)

The hex is defined by its **flat-to-flat width = 64 tiles (512 px)**. Everything else
derives from that one number:

| | tiles | px |
|---|---|---|
| flat-to-flat (width) | 64 | 512 |
| apothem (centre → flat) | 32 | 256 |
| circumradius = side length | 36.95 | 295.6 |
| corner-to-corner (height) | 73.90 | 591.2 |
| area | 3,547 cells | 227,023 px² |

A hex is **3.94x the 320x180 viewport by AREA** (3,547 cells vs 900). That is what
"3-4x the size of the viewport" meant — it is NOT 3-4 viewports across.

The island is **radius 8 = 217 hexes** (`3R² + 3R + 1`), ~770k cells, matching the
~200 playable tiles of the pre-pivot 15x15 grid.

Derived field constants:
- `core_hard_radius` = **40**. Must be ≥ the circumradius (36.95), because a hex's
  farthest points from its centre are its six corners, sitting at exactly the
  circumradius. 40 leaves ~3 tiles of margin. This is the all-plains start-hex
  guarantee, and it is the reason the number is 40 and not a round 32 or 64.
- `core_blend_radius` = **50**.
- `region_size` = **210** (~10-hex biome blobs, per `world_and_biomes.md`'s "organic
  blobs of roughly 8-20 tiles", where those tiles are hexes, not art tiles).
- `world_radius` = **500** (area-effective radius of the 217-hex island).
- **Origin = the CENTRE of cell `(0,0)`**, with core distance measured from cell
  centres. Without this convention the disc and the hex each sit half a tile off, and
  the all-plains guarantee gets decided by a float comparison at the hex corners.

**Ring-bands are cut** (2026-07-08). Nothing in the world wants concentric structure
any more. The only radial thing left is the soft harshness bias on each Voronoi
seed's draw, so a ring appearing in a render is a bug with no defender.

## 3. What THIS repo builds (TOOLS deltas — plan these)

### 3.1 Biome-set config for `procgen_tileset_build`
Assign the transition panels + the priority order + each biome's coastline block
in one declarative config. `procgen_tileset_build` already takes per-pack
`minifantasy_edges` terrain_assigns, so this is largely a new config shape, not new
tool code. Plan-time confirm: does the transparent-center transition block need any
builder change vs the existing land/water block? The footprint is identical; only
the "outside" pixels differ (transparent vs blue), so likely the builder just
consumes different source pixels, but verify the scan/animation paths don't assume
opaque edges.

### 3.2 Water animation as an optional per-biome feature
v2's `set_tile_animation_separation` water animation becomes an opt-in per-biome
thing (lakes), not the global bottom. Likely config usage only, no new tool code;
confirm at plan time.

### 3.3 Biome-field preview tool (headless)
A tuning/verification aid that renders the blob-biome field (radial/noise +
cellular-automata majority smoothing, 3 CA passes, seed-deterministic) so field
params can be authored and eyeballed before they go into the game. This is the
tools-side of the field work; the RUNTIME field generator that the game's streamer
calls lives game-side (§4). Follows the v2 tool lineage (the deferred
`procgen_worldgen_preview`, T3). Field is computed per bake region with a margin =
CA passes + matcher ring = 4 cells; margin cells computed-but-not-committed so
adjacent regions seam-match deterministically.

### 3.4 (confirm at plan) terrain-audit coverage
Whether `procgen_terrain_audit` needs to report biome-set / transition coverage the
way it reports single-terrain coverage today.

## 4. What the GAME repo builds (reference only — reconciled separately)

Handled in `squareds/project1`, being reconciled against `world_and_biomes.md`.
NOT planned here. Captured so the game track has the decisions we locked:

- **Matcher predicate flip:** the corner-Wang matcher (ships game-side at
  `systems/worldgen/terrain_matcher.gd`, spec-locked here in
  `tests/test_terrain_matcher_spec.py`) flips its predicate from "is land" to "is
  biome Y". Mechanically sound (§5).
- **Two overlay draw passes:** coastline pass (land cells adjacent to a lake draw
  their own coastline block toward the lake) then land-land panel pass (lower cells
  draw higher neighbors' transparent panels). Coastline below panels; they target
  different corners and compose.
- **Runtime biome-field generator:** the field the streamer bakes from (CA, 3
  passes, seed-deterministic, per-region with a 4-cell margin).
- **Hex map:** axial macro-grid, per-hex `locked | unlocked`, unlock gates
  visibility + movement + building.
- **Fog shader:** a separate overlay CanvasItem (not a terrain layer) owning the
  hex uniforms; samples a one-texel-per-hex reveal mask (0..1), world→axial→texel,
  hex-shaped falloff; a per-hex timer drives the texel 0→1 for a feathered reveal.
  Terrain layers never sample it, so the decoupling holds.
- **Streamer + region bake + eviction:** margin 4, margins computed-but-not-
  committed, resident window = current hex + 6 neighbors, evict tile data beyond
  (keep unlock state), re-bake on approach (deterministic).
- **Save format:** `seed + per-hex unlock state` only; terrain re-bakes from seed.

Reconciliation with `world_and_biomes.md` (game track, not this repo).

**Settled 2026-07-08.** Hex replaces the 15x15 square grid, island radius 8 = 217
hexes. The canonical hex is 64 tiles flat-to-flat (§2.2). Ring-bands are cut. Hex
unlock is **coin-based to start**, replacing the causeway build order that all-land
made meaningless.

**Still open on the game track.** (1) Fog vs the biome-tinted haze, which deliberately
let you read region shapes for route planning — fog hides, haze reveals. (2) Surfaced
by the two cuts above: **both original unlock gates are now gone.** The causeway was
the economy gate; the band artifact was the skill gate. With coins the only gate, the
coin curve must scale with ring distance, or nothing stops a player buying straight
out to the ice rim and the gentle→harsh gradient gates nothing — it becomes scenery.

## 5. Verified reuse (grounded against `src/godot_mcp/procgen.py`, 2026-07-06)

- `minifantasy_edges` is a 3x5 (15-cell) MATCH_CORNERS block whose `(1,1)` cell
  carries the empty corner signature `()` — matches "transparent center at the
  (1,1) empty-signature class".
- `corner_signature_key` is a pure function of a boolean `mask(x,y)` predicate, so
  flipping the predicate to "is biome Y" is mechanically sound.
- `procgen_tileset_build` and the `_STRATEGY_TABLES` (blob47 / blob16_sides /
  blob16_corners / minifantasy_edges) are present and reusable.
- Corrections to the first draft: the "organic/island-mask generator" is NEW work
  (prototyped in the game repo's `procgen_tiler` dock + a throwaway sample, never a
  shipped tool). The `procgen_tiler` dock DOES exist — built + committed to the game
  repo today (`addons/procgen_tiler/`, commit 95bfa4b) — it is game-repo work, not a
  tools transfer.

## 6. Non-goals / deferred

- True hex-shaped terrain tiles (needs hex-authored edge art; this pack is square).
- Rivers-as-flow, biome sub-variants, weather, multiplayer.
