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

Open reconciliation with `world_and_biomes.md` (for the game agent, not this repo):
all-land removes the causeway economy gate; hex replaces the 15x15 square grid;
fog vs biome-tinted haze; tile-size / streaming numbers. These are game-design
rulings, resolved on the game track.

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
