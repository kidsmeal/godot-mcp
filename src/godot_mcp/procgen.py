"""procgen: the procgen tool suite (`procgen_*`).

Phase 0 stood up the headless round-trip harness (a throwaway `procgen_ping`
probe, now removed). Phase 1 lands the first real tool, `tileset_build`, and
hardens the shared harness the remaining five tools inherit.

Temp-script pattern (decide-once, documented here so later phases copy it
verbatim rather than re-inventing it):

  - Compose a `.gd` source string in Python. It MUST `extends SceneTree` so it
    runs headless via `--script` without popping a blocking editor dialog
    (`runner.run_script` already refuses non-SceneTree/MainLoop scripts for
    this reason; `runner.run_temp_probe` skips that guard because IT is the
    one writing the temp file, so the composed source here always declares
    `extends SceneTree` itself).
  - Hand the source to `runner.run_temp_probe(source, timeout=...)`. That
    helper writes the source to a unique OS-temp `.gd` file, runs it headless
    via the same `_run()` used by every other tool (so GODOT_BIN/GODOT_PROJECT
    resolution, `--log-file` capture, and timeout handling are identical
    across the whole server), and deletes the temp `.gd` (and any `.gd.uid`
    sibling Godot emits) in a `finally` block — no leak into the project or
    OS temp dir even on a crash. Do NOT hand-roll a second subprocess path.
  - The composed script prints a JSON payload (single- or multi-line between
    the sentinels — the parser tolerates both) wrapped between per-run sentinel
    markers on their own lines:

        print("PROCGEN_JSON_BEGIN:<nonce>")
        print(JSON.stringify({...}))
        print("PROCGEN_JSON_END:<nonce>")

    The `<nonce>` is a fresh random hex token generated per run in Python and
    interpolated into BOTH the composed script and the parser regex. This is
    collision-resistant: a payload that happens to contain the literal string
    "PROCGEN_JSON_END" (plausible once tools dump arbitrary project data — file
    paths, config values, atlas names) can no longer truncate parsing early,
    because it cannot also contain that run's random nonce. `make_sentinels()`
    + `parse_sentinel_json()` below are the shared harness helpers; every
    `procgen_*` tool composes its report through them.
  - `quit()` at the end of `_initialize()` so the SceneTree exits promptly.
"""
from __future__ import annotations

import json
import secrets
import tomllib
from pathlib import Path

from godot_mcp import config, runner

# ---------------------------------------------------------------------------
# Hardened sentinel harness (shared by every procgen_* tool)
# ---------------------------------------------------------------------------

_SENTINEL_BEGIN = "PROCGEN_JSON_BEGIN"
_SENTINEL_END = "PROCGEN_JSON_END"


def make_sentinels() -> tuple[str, str, str]:
    """Return (nonce, begin_marker, end_marker) for one probe run.

    The nonce is a fresh random hex token, appended to both markers so a JSON
    payload can never contain the *exact* end marker for this run (see the
    module docstring's collision note). Compose the GDScript's begin/end prints
    with the returned markers and parse the output with `parse_sentinel_json`.
    """
    nonce = secrets.token_hex(8)
    return nonce, f"{_SENTINEL_BEGIN}:{nonce}", f"{_SENTINEL_END}:{nonce}"


def parse_sentinel_json(out: str, nonce: str) -> tuple[dict | None, str]:
    """Extract and parse the JSON payload between this run's nonce'd sentinels.

    Returns (payload, ""). On failure returns (None, reason) where reason is a
    short human string. Splits on the exact nonce'd markers rather than a regex
    over the bare marker, so an embedded literal "PROCGEN_JSON_END" cannot
    truncate the block.
    """
    begin = f"{_SENTINEL_BEGIN}:{nonce}"
    end = f"{_SENTINEL_END}:{nonce}"
    if begin not in out:
        return None, "no PROCGEN_JSON begin sentinel in output"
    after = out.split(begin, 1)[1]
    if end not in after:
        return None, "no PROCGEN_JSON end sentinel in output"
    body = after.split(end, 1)[0].strip()
    try:
        return json.loads(body), ""
    except json.JSONDecodeError as e:
        return None, f"malformed JSON between sentinels: {e}"


# ---------------------------------------------------------------------------
# blob autotile strategy tables (pure Python data — tested directly)
# ---------------------------------------------------------------------------
#
# These map a standard blob-layout grid offset (col, row) to the set of terrain
# peering bits a tile at that offset must carry, for the water-bottom law's
# itself-vs-empty signatures. The engine's built-in terrain solver is NEVER
# used to derive or apply these (issues #76493 diagonal/wrong-terrain and
# #89844 ignored diagonal bits — both still open on 4.6.2 AND 4.7-stable as of
# 2026-07-03; re-audit by grepping these numbers on any engine bump). We assign
# peering bits directly to TileData and let the in-house matcher read them.

# Godot TileSet.CellNeighbor bit names, by our compass shorthand.
# Sides for MATCH_SIDES / MATCH_CORNERS_AND_SIDES:
_SIDE_BITS = {"N": "TOP_SIDE", "E": "RIGHT_SIDE", "S": "BOTTOM_SIDE", "W": "LEFT_SIDE"}
# Diagonal corners, used by BOTH MATCH_CORNERS_AND_SIDES and MATCH_CORNERS.
# The axis-aligned CellNeighbor.*_CORNER bits (TOP_CORNER, RIGHT_CORNER, ...)
# are for hex/isometric grids only — `is_valid_terrain_peering_bit` rejects
# them on a square-grid MATCH_CORNERS terrain set, which is the only grid
# shape this module builds. Do not reintroduce an axis-aligned corner table.
_CORNER_BITS = {
    "NE": "TOP_RIGHT_CORNER",
    "SE": "BOTTOM_RIGHT_CORNER",
    "SW": "BOTTOM_LEFT_CORNER",
    "NW": "TOP_LEFT_CORNER",
}

_SIDES = ("N", "E", "S", "W")
_CORNERS = ("NE", "SE", "SW", "NW")
# The full-interior (all 4 corners land) MATCH_CORNERS signature: the solid
# ground fill tile. This is the one class the 15-cell minifantasy_edges pond
# block never depicts, supplied instead by the `interior` param (see
# `_resolve_assign_bits`). Kept as the diagonal `_CORNER_BITS` in a fixed order
# so an `interior` cell and the audit's expected all-corners class produce the
# identical signature key.
_ALL_CORNER_BITS: list[str] = [_CORNER_BITS[c] for c in _CORNERS]
# A diagonal corner is only "filled" if BOTH its adjacent sides are filled;
# this is what collapses the 256 raw 8-neighbor cases to 47 canonical classes.
_CORNER_ADJ = {"NE": ("N", "E"), "SE": ("S", "E"), "SW": ("S", "W"), "NW": ("N", "W")}


def _canonical_blob47_configs() -> list[tuple[tuple[str, ...], tuple[str, ...]]]:
    """The 47 canonical (sides, corners) neighbor classes for
    MATCH_CORNERS_AND_SIDES, in a deterministic order.

    Enumerated from the corner-validity rule (a corner counts only when both
    adjacent sides are filled), which yields exactly 47 classes. Ordering is
    stable: fewer sides first, then side-index order, then fewer corners, then
    corner-index order. Config 0 is the isolated tile (no neighbors); config 46
    is the full-interior tile (all 8 neighbors).
    """
    side_idx = {s: i for i, s in enumerate(_SIDES)}
    corner_idx = {c: i for i, c in enumerate(_CORNERS)}
    configs: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    for smask in range(16):
        sides = tuple(_SIDES[i] for i in range(4) if smask & (1 << i))
        sset = set(sides)
        eligible = [c for c in _CORNERS if _CORNER_ADJ[c][0] in sset and _CORNER_ADJ[c][1] in sset]
        for cmask in range(1 << len(eligible)):
            corners = tuple(eligible[i] for i in range(len(eligible)) if cmask & (1 << i))
            configs.append((sides, corners))

    def _key(cfg: tuple[tuple[str, ...], tuple[str, ...]]) -> tuple:
        s, c = cfg
        return (len(s), tuple(sorted(side_idx[x] for x in s)), len(c), tuple(sorted(corner_idx[x] for x in c)))

    configs.sort(key=_key)
    return configs


def blob47_table(width: int = 8) -> dict[tuple[int, int], list[str]]:
    """Map grid offset (col, row) -> list of CellNeighbor bit names for a
    standard 47-tile blob layout under MATCH_CORNERS_AND_SIDES.

    The 47 canonical classes are laid out row-major at *width* columns (the
    common blob-sheet arrangement). Offsets are relative to the config's
    `origin`. Bit names are the engine's `TileSet.CellNeighbor` enum member
    names (e.g. "TOP_SIDE", "BOTTOM_RIGHT_CORNER").
    """
    table: dict[tuple[int, int], list[str]] = {}
    for i, (sides, corners) in enumerate(_canonical_blob47_configs()):
        col, row = i % width, i // width
        bits = [_SIDE_BITS[s] for s in sides] + [_CORNER_BITS[c] for c in corners]
        table[(col, row)] = bits
    return table


def blob16_sides_table(width: int = 4) -> dict[tuple[int, int], list[str]]:
    """Map grid offset -> side-bit names for a 16-tile blob under MATCH_SIDES.

    All 16 side masks are valid (no corners), laid out row-major at *width*.
    """
    table: dict[tuple[int, int], list[str]] = {}
    for smask in range(16):
        sides = [_SIDES[i] for i in range(4) if smask & (1 << i)]
        col, row = smask % width, smask // width
        table[(col, row)] = [_SIDE_BITS[s] for s in sides]
    return table


def blob16_corners_table(width: int = 4) -> dict[tuple[int, int], list[str]]:
    """Map grid offset -> corner-bit names for a 16-tile blob under
    MATCH_CORNERS.

    On a square grid, MATCH_CORNERS's valid peering bits are the 4 DIAGONAL
    corner bits (TOP_RIGHT_CORNER, BOTTOM_RIGHT_CORNER, BOTTOM_LEFT_CORNER,
    TOP_LEFT_CORNER) — the same `_CORNER_BITS` blob47 uses for its corners.
    Unlike blob47's corners (which require both adjacent sides filled),
    MATCH_CORNERS has no side bits to gate on, so all 16 subsets of the 4
    diagonal corners are valid classes, laid out row-major at *width*.
    """
    table: dict[tuple[int, int], list[str]] = {}
    for cmask in range(16):
        corners = [_CORNERS[i] for i in range(4) if cmask & (1 << i)]
        col, row = cmask % width, cmask // width
        table[(col, row)] = [_CORNER_BITS[c] for c in corners]
    return table


# The Minifantasy biome edge block: a fixed 3-wide x 5-tall = 15-tile
# CORNER-based (Wang) autotile shared by every Minifantasy biome sheet
# (ForgottenPlains, DesolateDesert, ... — only the origin, land palette, and
# animation-frame layout differ per sheet). Each cell depicts which of its 4
# DIAGONAL corners are LAND (the terrain); off-corner is water. The land-corner
# set per block cell was read EMPIRICALLY off the real ForgottenPlains
# grass-water block (cols 25-27, rows 3-7) at high zoom and CONFIRMED
# pixel-for-pixel identical on the DesolateDesert grass-water block (cols 20-22,
# rows 5-9), so the arrangement is a shared family constant, not per-pack.
#
#   block layout (block-relative col, row) -> LAND diagonal corners:
#     (0,0) TL,TR,BL   (1,0) TL,TR      (2,0) TL,TR,BR      <- pond top ring
#     (0,1) TL,BL      (1,1) (none)     (2,1) TR,BR         <- pond side ring + water center
#     (0,2) TL,BL,BR   (1,2) BL,BR      (2,2) TR,BL,BR      <- pond bottom ring
#     (0,3) TL         (1,3) TR         (2,3) TL,BR         <- single/diagonal-corner diamonds
#     (0,4) BL         (1,4) BR         (2,4) TR,BL         <- single/diagonal-corner diamonds
#
# The 15 cells cover 15 of the 16 MATCH_CORNERS classes with NO duplicates; the
# only class absent is the full-interior (all 4 corners land) tile, which a pond
# ring never depicts. A bare `minifantasy_edges` sheet therefore audits 15/16
# covered, 1 missing (the all-corners interior). The `interior` param on the
# terrain_assign (see `_resolve_assign_bits`) supplies that lone class from the
# biome's SOLID GROUND fill cells, taking a full-biome ground layer to 16/16;
# multiple interior cells are variants of the all-corners signature (the
# matcher's seeded pick scatters them across the island interior).
_MINIFANTASY_EDGES_LAND_CORNERS: dict[tuple[int, int], tuple[str, ...]] = {
    (0, 0): ("NW", "NE", "SW"),
    (1, 0): ("NW", "NE"),
    (2, 0): ("NW", "NE", "SE"),
    (0, 1): ("NW", "SW"),
    (1, 1): (),
    (2, 1): ("NE", "SE"),
    (0, 2): ("NW", "SW", "SE"),
    (1, 2): ("SW", "SE"),
    (2, 2): ("NE", "SW", "SE"),
    (0, 3): ("NW",),
    (1, 3): ("NE",),
    (2, 3): ("NW", "SE"),
    (0, 4): ("SW",),
    (1, 4): ("SE",),
    (2, 4): ("NE", "SW"),
}


def minifantasy_edges_table() -> dict[tuple[int, int], list[str]]:
    """Map block-relative offset (col, row) -> diagonal corner-bit names for the
    Minifantasy 3x5 biome edge block under MATCH_CORNERS.

    The 15-cell arrangement is a fixed family constant
    (`_MINIFANTASY_EDGES_LAND_CORNERS`, read off the real ForgottenPlains and
    DesolateDesert sheets — see that dict's comment). Offsets are block-relative
    (cols 0-2, rows 0-4); `_resolve_assign_bits` translates them by the
    terrain_assign's `origin` so one table serves every biome sheet at its own
    atlas position. Bit names are the same DIAGONAL `_CORNER_BITS` the S1 matcher
    and `blob16_corners` use, never the axis-aligned hex/iso CORNER bits.
    """
    return {
        (col, row): [_CORNER_BITS[c] for c in corners]
        for (col, row), corners in _MINIFANTASY_EDGES_LAND_CORNERS.items()
    }


_STRATEGY_TABLES = {
    "blob47": blob47_table,
    "blob16_sides": blob16_sides_table,
    "blob16_corners": blob16_corners_table,
    "minifantasy_edges": minifantasy_edges_table,
}

# All 8 CellNeighbor bit names this module knows about (sides + diagonal
# corners — the only bits valid on the square grids this module builds), used
# by the audit tool to query `is_valid_terrain_peering_bit` per tile —
# mode-agnostic, since the engine itself already knows which bits are valid
# for a tile's terrain set. Axis-aligned CORNER bits (TOP_CORNER, ...) are for
# hex/isometric grids and are deliberately excluded so they can never be
# emitted or queried here.
_ALL_BIT_NAMES: tuple[str, ...] = (
    *_SIDE_BITS.values(),
    *_CORNER_BITS.values(),
)

_MODE_TABLE_FN = {
    "MATCH_CORNERS_AND_SIDES": blob47_table,
    "MATCH_SIDES": blob16_sides_table,
    "MATCH_CORNERS": blob16_corners_table,
}


def expected_signature_set(mode: str) -> set[frozenset[str]]:
    """The expected itself-vs-empty peering-bit signature classes for a
    terrain set's *mode*, DERIVED from the mode's valid-bit enumeration — never
    a hardcoded count. Reuses the same canonical tables `tileset_build` uses to
    lay out blob sheets (`blob47_table` for MATCH_CORNERS_AND_SIDES,
    `blob16_sides_table` / `blob16_corners_table` for the other two modes), so
    the audit's "what should exist" checklist and the builder's "where do these
    classes live on a blob sheet" layout can never drift apart. A signature is
    a frozenset of CellNeighbor bit names (order-independent); the number of
    classes falls out of the table's size (47 for corners+sides, 16 for the
    single-axis modes) rather than being written down as a literal anywhere.

    Raises ValueError for a mode this module doesn't recognize.
    """
    fn = _MODE_TABLE_FN.get(mode)
    if fn is None:
        raise ValueError(f"unknown terrain set mode: {mode!r}")
    return {frozenset(bits) for bits in fn().values()}


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


class ConfigError(ValueError):
    """A tileset_build config failed validation (reported, not raised to user)."""


_VARIANT_TYPES = {"string": "TYPE_STRING", "int": "TYPE_INT", "float": "TYPE_FLOAT", "bool": "TYPE_BOOL"}


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise ConfigError(msg)


def _is_int_pair(v: object) -> bool:
    return isinstance(v, list) and len(v) == 2 and all(isinstance(n, int) for n in v)


# Default per-tile weight when a variant carries no explicit weight — the
# unweighted case. Weights are RELATIVE (normalized at pick time), so a default
# of 1.0 across every tile reproduces the prior uniform seeded pick exactly.
_DEFAULT_WEIGHT = 1.0

# The custom-data layer weights are baked into. A float per tile; the audit
# reads it back into each coverage-dict variant entry (default 1.0 when absent).
# This name is the build<->audit<->matcher contract, keep it stable.
_WEIGHT_LAYER_NAME = "weight"


def _parse_weighted_cell(entry: object) -> tuple[tuple[int, int], float] | None:
    """Parse one `interior` entry into ((col, row), weight), or None if malformed.

    Two accepted shapes (chosen ONE clean form — the 3-element list — over a
    parallel dict shape so TOML/JSON configs stay a single list-of-lists):
      - bare `[col, row]`            -> default weight (unweighted, back-compat)
      - weighted `[col, row, weight]` -> explicit RELATIVE weight (positive number)
    Returns None for anything else (wrong length, non-int coords, non-positive or
    non-numeric weight) so callers can raise a clean ConfigError. Weights ride the
    same list rail variants already use, so any future variant tile (edge variants)
    can carry a weight the same way.
    """
    if not isinstance(entry, list):
        return None
    if len(entry) == 2:
        if not all(isinstance(n, int) for n in entry):
            return None
        return (int(entry[0]), int(entry[1])), _DEFAULT_WEIGHT
    if len(entry) == 3:
        col, row, weight = entry
        if not (isinstance(col, int) and isinstance(row, int)):
            return None
        # bool is an int subclass; reject True/False as a weight explicitly.
        if not (isinstance(weight, (int, float)) and not isinstance(weight, bool)):
            return None
        if not (weight > 0):
            return None
        return (int(col), int(row)), float(weight)
    return None


def _base_region_cells(base_region: list) -> set[tuple[int, int]]:
    """Expand a validated `base_region` ([[x0,y0],[x1,y1]] inclusive rect) into
    the set of (x, y) base-tile coords it covers. Callers must validate the
    shape first (`validate_config` does, via the required-animation-fields
    check) — this assumes a well-formed pair of int pairs.
    """
    corner0, corner1 = base_region[0], base_region[1]
    bx0, by0 = int(corner0[0]), int(corner0[1])
    bx1, by1 = int(corner1[0]), int(corner1[1])
    return {(bx, by) for by in range(by0, by1 + 1) for bx in range(bx0, bx1 + 1)}


def validate_config(cfg: dict) -> dict:
    """Validate a tileset_build config dict and return a normalized copy.

    Enforces (per the water-bottom law): at most one terrain per terrain set,
    and `mode == "default"` for any animation group whose OWN base cells
    overlap terrain-assigned cells (water-bearing edges must start in phase) —
    a decor animation on non-terrain cells may use `random_start` even when the
    same atlas also carries terrain-bearing tiles elsewhere. Also validates each
    animation group's required fields (base_region shape, frames, frame_offset,
    duration). Raises ConfigError on the first violation.
    """
    _require(isinstance(cfg.get("tileset"), dict), "config missing [tileset] section")
    tile_size = cfg["tileset"].get("tile_size")
    _require(
        isinstance(tile_size, list) and len(tile_size) == 2 and all(isinstance(n, int) for n in tile_size),
        "[tileset].tile_size must be a [int, int] pixel size",
    )

    atlases = cfg.get("atlas") or []
    _require(isinstance(atlases, list) and len(atlases) >= 1, "config needs at least one [[atlas]]")
    atlas_ids: set[str] = set()
    for a in atlases:
        aid = a.get("id")
        _require(isinstance(aid, str) and aid != "", "each [[atlas]] needs a string id")
        _require(aid not in atlas_ids, f"duplicate atlas id: {aid}")
        atlas_ids.add(aid)
        _require(isinstance(a.get("texture"), str) and a["texture"] != "", f"atlas {aid} needs a texture path")
        scan = a.get("scan", "non_transparent")
        _require(
            scan in ("non_transparent", "all", "explicit"),
            f"atlas {aid}: scan must be 'non_transparent', 'all', or 'explicit' (got {scan!r})",
        )
        if scan == "explicit":
            _require(isinstance(a.get("tiles"), list) and a["tiles"], f"atlas {aid}: scan='explicit' needs a [[atlas.tiles]] list")

    # Terrain sets: one terrain per set (the law).
    terrain_sets = cfg.get("terrain_set") or []
    terrain_names: dict[str, int] = {}  # terrain name -> terrain_set index
    for ti, ts in enumerate(terrain_sets):
        mode = ts.get("mode", "match_corners_and_sides")
        _require(
            mode in ("match_corners_and_sides", "match_corners", "match_sides"),
            f"terrain_set {ti}: unknown mode {mode!r}",
        )
        terrains = ts.get("terrains") or []
        _require(
            len(terrains) <= 1,
            f"terrain_set {ti}: {len(terrains)} terrains declared, but the water-bottom law allows at most ONE terrain per terrain set",
        )
        for t in terrains:
            name = t.get("name")
            _require(isinstance(name, str) and name != "", f"terrain_set {ti}: each terrain needs a name")
            _require(name not in terrain_names, f"duplicate terrain name across terrain sets: {name}")
            terrain_names[name] = ti

    # Terrain assignments: strategy known, atlas + terrain resolve.
    for asn in cfg.get("terrain_assign") or []:
        strat = asn.get("strategy")
        _require(
            strat in ("blob47", "blob16_sides", "blob16_corners", "minifantasy_edges", "explicit"),
            f"terrain_assign: unknown strategy {strat!r}",
        )
        _require(asn.get("atlas") in atlas_ids, f"terrain_assign references unknown atlas {asn.get('atlas')!r}")
        _require(asn.get("terrain") in terrain_names, f"terrain_assign references unknown terrain {asn.get('terrain')!r}")
        if strat == "explicit":
            _require(isinstance(asn.get("tiles"), list) and asn["tiles"], "terrain_assign strategy='explicit' needs a per-tile bits list")
        if "interior" in asn:
            _require(
                strat == "minifantasy_edges",
                "terrain_assign: `interior` is only valid with strategy='minifantasy_edges' (its 3x5 edge "
                "block omits the full-interior tile). The blob47/blob16 tables already cover the interior "
                "class; for 'explicit', list the interior tile in `tiles` with its 4 diagonal corner bits.",
            )
            interior = asn["interior"]
            _require(
                isinstance(interior, list),
                f"terrain_assign: `interior` must be a list of [col, row] (optionally [col, row, weight]) "
                f"entries, got {interior!r}",
            )
            for entry in interior:
                _require(
                    _parse_weighted_cell(entry) is not None,
                    f"terrain_assign: `interior` must be [col, row] int pairs or [col, row, weight] "
                    f"entries with a positive number weight; bad entry {entry!r}",
                )

    # Animation groups: atlas resolves; water-bearing groups (the animated
    # TILE ITSELF carries a terrain) must be mode='default' so coastline water
    # stays in phase. This is a TILE-level rule, not an atlas-level one: a
    # decor tile with no terrain may use 'random_start' even in an atlas that
    # also has terrain-bearing tiles elsewhere (mixed ground+decor sheets are
    # common). Resolve each terrain_assign's per-cell coords once so every
    # animation group's base-cell footprint can be checked against them.
    terrain_cells_by_atlas: dict[str, set[tuple[int, int]]] = {}
    for asn in cfg.get("terrain_assign") or []:
        aid = asn.get("atlas")
        if aid not in atlas_ids:
            continue
        origin = tuple(asn.get("origin", [0, 0]))
        try:
            bits_by_coords = _resolve_assign_bits(asn, origin)  # type: ignore[arg-type]
        except (KeyError, TypeError):
            # Malformed explicit tile entries etc. are reported by the
            # terrain_assign loop above; skip here rather than double-report.
            continue
        terrain_cells_by_atlas.setdefault(aid, set()).update(bits_by_coords.keys())

    for an in cfg.get("animation") or []:
        aid = an.get("atlas")
        _require(aid in atlas_ids, f"animation references unknown atlas {aid!r}")

        # Required animation-group fields, validated here (as ConfigError)
        # BEFORE any compose-time indexing touches them — a malformed/missing
        # field must come back as a structured report, never a raw Python
        # stack trace (mcp cross-cutting discipline).
        base_region = an.get("base_region")
        _require(
            isinstance(base_region, list) and len(base_region) == 2 and all(_is_int_pair(c) for c in base_region),
            f"animation on atlas {aid!r}: base_region must be [[x0,y0],[x1,y1]] (int tile-coord pairs), got {base_region!r}",
        )
        assert isinstance(base_region, list)
        bx0, by0 = int(base_region[0][0]), int(base_region[0][1])
        bx1, by1 = int(base_region[1][0]), int(base_region[1][1])
        _require(
            bx0 <= bx1 and by0 <= by1,
            f"animation on atlas {aid!r}: base_region [[x0,y0],[x1,y1]] must have x0<=x1 and y0<=y1, got {base_region!r}",
        )
        _require(isinstance(an.get("frames"), int) and an["frames"] >= 2, f"animation on atlas {aid!r}: needs an int frames >= 2")
        fo = an.get("frame_offset", [1, 0])
        _require(
            _is_int_pair(fo),
            f"animation on atlas {aid!r}: frame_offset must be an [int, int] pair, got {fo!r}",
        )
        duration = an.get("duration", 1.0)
        _require(
            isinstance(duration, (int, float)) and not isinstance(duration, bool) and duration > 0,
            f"animation on atlas {aid!r}: duration must be a positive number, got {duration!r}",
        )

        mode = an.get("mode", "default")
        _require(mode in ("default", "random_start"), f"animation mode must be 'default' or 'random_start' (got {mode!r})")
        # Godot tile animation only supports contiguous horizontal or vertical
        # frame strips (see compose_build_script). Reject other offsets early.
        _require(
            (fo == [1, 0]) or (fo == [0, 1]),
            f"animation on atlas {aid!r}: frame_offset must be [1,0] (horizontal) or [0,1] (vertical); got {fo}",
        )
        if mode != "default":
            terrain_cells = terrain_cells_by_atlas.get(aid, set())
            overlap = _base_region_cells(base_region) & terrain_cells
            if overlap:
                sample = ", ".join(str(c) for c in sorted(overlap)[:5])
                raise ConfigError(
                    f"animation on atlas {aid!r} covers terrain-assigned tile(s) ({sample}) but uses "
                    f"mode={mode!r}; water-bearing (terrain) tiles MUST use mode='default' so the engine starts "
                    "all water animations in phase (coastline sync contract) — a decor tile with no terrain on "
                    "the same atlas may still use 'random_start'"
                )

    # Custom data layers: known types. `weight` is a RESERVED float layer (the
    # per-variant weighting contract the build/audit/matcher share) — a config
    # that declares its own `weight` layer with any other type would silently
    # break weight reads, so require float explicitly instead of letting a
    # mistyped layer through the generic type check.
    for cd in (cfg.get("custom_data") or {}).get("layers") or []:
        _require(cd.get("type") in _VARIANT_TYPES, f"custom_data layer {cd.get('name')!r}: unsupported type {cd.get('type')!r}")
        if cd.get("name") == _WEIGHT_LAYER_NAME:
            _require(
                cd.get("type") == "float",
                f"custom_data layer {_WEIGHT_LAYER_NAME!r} is reserved for per-variant weighting and must be "
                f"type = \"float\", got {cd.get('type')!r}",
            )

    return cfg


def load_config(config_path: str) -> dict:
    """Read + validate a tileset_build config (TOML or JSON). Raises ConfigError.

    Dispatches on the file extension: `.json` parses via `json.loads`, anything
    else (including `.toml`) parses via `tomllib.loads` (the historical
    default, kept so extension-less paths still work). Both branches produce
    the same plain dict shape, which then runs through the same
    `validate_config` — the plan's config schema (`tileset_build`'s "TOML/JSON
    file") does not vary by format, only by syntax.
    """
    try:
        raw = Path(config_path).read_bytes()
    except OSError as e:
        raise ConfigError(f"could not read config {config_path}: {e}") from e
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ConfigError(f"config {config_path} is not valid UTF-8: {e}") from e

    if Path(config_path).suffix.lower() == ".json":
        try:
            cfg = json.loads(text)
        except json.JSONDecodeError as e:
            raise ConfigError(f"config {config_path} is not valid JSON: {e}") from e
    else:
        try:
            cfg = tomllib.loads(text)
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"config {config_path} is not valid TOML: {e}") from e

    if not isinstance(cfg, dict):
        raise ConfigError(f"config {config_path} must parse to an object/table at the top level")
    return validate_config(cfg)


# ---------------------------------------------------------------------------
# GDScript composition
# ---------------------------------------------------------------------------


def _resolve_assign_bits(asn: dict, atlas_origin: tuple[int, int]) -> dict[tuple[int, int], list[str]]:
    """Resolve a terrain_assign into {atlas_coords: [bit names]} for the GDScript.

    For blob strategies, pull the offset->bits table and translate by origin.
    For 'explicit', read per-tile bits straight from the config.

    The optional `interior` param (a list of ABSOLUTE atlas cells, each `[col,
    row]` or `[col, row, weight]`) supplies the full-interior all-4-corners
    signature the strategy's own table may omit — specifically
    `minifantasy_edges`, whose 15-cell pond block covers only 15 of the 16
    MATCH_CORNERS classes (the solid-ground fill is absent). Each interior cell
    is assigned exactly the 4 diagonal corner bits, so with >=1 interior cell the
    sheet covers 16/16; multiple interior cells are all the same all-corners
    signature and surface in the audit as variants (the matcher's WEIGHTED seeded
    pick scatters them across the island interior by their weights). Interior
    coords are ABSOLUTE (not block-relative), so they are NOT translated by
    origin. The optional per-cell weight is handled separately by
    `_resolve_assign_weights` (baked into the `weight` custom-data layer) — this
    function only maps coords -> bits.
    """
    strat = asn["strategy"]
    if strat == "explicit":
        out: dict[tuple[int, int], list[str]] = {}
        for t in asn["tiles"]:
            coords = tuple(t["coords"])
            out[(coords[0], coords[1])] = list(t.get("bits", []))
        return out
    table = _STRATEGY_TABLES[strat]()
    ox, oy = asn.get("origin", list(atlas_origin))
    resolved = {(ox + col, oy + row): bits for (col, row), bits in table.items()}
    for entry in asn.get("interior", []):
        cell, _weight = _parse_weighted_cell(entry) or ((int(entry[0]), int(entry[1])), _DEFAULT_WEIGHT)
        resolved[cell] = list(_ALL_CORNER_BITS)
    return resolved


def _resolve_assign_weights(asn: dict, atlas_origin: tuple[int, int]) -> dict[tuple[int, int], float]:
    """Resolve a terrain_assign into {atlas_coords: weight} for the GDScript.

    The parallel rail to `_resolve_assign_bits`: weights ride the SAME per-tile
    plumbing bits do, so any variant tile can carry a relative weight. Only cells
    with an EXPLICIT weight are returned; cells without one default to
    `_DEFAULT_WEIGHT` at bake time (the build script writes 1.0 for every
    terrain-bearing tile absent from this map). Today only `interior` entries can
    carry a weight (`[col, row, weight]`); edge/blob variants are a future
    extension that would populate this map the same way. Interior coords are
    ABSOLUTE (not origin-translated), matching `_resolve_assign_bits`.
    """
    weights: dict[tuple[int, int], float] = {}
    for entry in asn.get("interior", []):
        parsed = _parse_weighted_cell(entry)
        if parsed is None:
            continue
        cell, weight = parsed
        if weight != _DEFAULT_WEIGHT:
            weights[cell] = weight
    return weights


def _gd_vec2i(x: int, y: int) -> str:
    return f"Vector2i({x}, {y})"


def compose_build_script(cfg: dict, out_path_res: str, nonce: str) -> str:
    """Compose the single GDScript that builds and saves the TileSet.

    The op-order below is load-bearing (verified engine facts, procgen-tools.md
    §1): create TileSet -> custom-data layer, then physics/nav layers IF the
    config actually declares them (P1-review carry-in: no more unconditional
    empty nav layer on every tileset) -> terrain sets + terrains -> per atlas
    TileSetAtlasSource (texture, texture_region_size) -> apply animation map +
    RESERVE frame regions -> scan remaining sheet OR take explicit tiles ->
    create_tile per base cell + animation columns/frames/duration/mode -> per
    tile get_tile_data(coords, 0): terrain_set FIRST, then terrain, then
    peering bits, then collision polygons + custom data -> ResourceSaver.save
    -> reload sanity check.
    """
    begin = f"{_SENTINEL_BEGIN}:{nonce}"
    end = f"{_SENTINEL_END}:{nonce}"

    ts = cfg["tileset"]
    tile_size = ts["tile_size"]

    # Build a fully-resolved plan dict in Python and hand it to the GDScript as
    # a JSON literal — the GDScript stays a dumb executor of a validated plan.
    physics_full_square = (cfg.get("physics") or {}).get("default_full_square") or []
    plan: dict = {
        "tile_size": [tile_size[0], tile_size[1]],
        "custom_data": [],
        "physics_full_square": physics_full_square,
        # P1-review carry-in: layer creation is conditional on the config
        # actually declaring collision/navigation, so a plain tileset doesn't
        # carry an unused empty nav layer (or an unused physics layer). The
        # config currently has no [navigation] section at all — navigation
        # layers are only ever created if a future config section asks for
        # one — so `has_navigation` is wired for that but always False today.
        "has_physics": bool(physics_full_square),
        "has_navigation": False,
        "terrain_sets": [],
        "terrain_index": {},  # terrain name -> [set_idx, terrain_idx]
        "atlases": [],
    }

    for cd in (cfg.get("custom_data") or {}).get("layers") or []:
        plan["custom_data"].append({"name": cd["name"], "type": _VARIANT_TYPES[cd["type"]]})

    # --- per-variant weighting bookkeeping ---------------------------------
    # Weights travel WITH each tile in a `weight` custom-data layer (float,
    # default 1.0). The layer is RESERVED (validate_config requires it be
    # float if the config declares it itself). It comes to exist one of two
    # ways: the config declares it directly (user-declared, already in
    # plan["custom_data"] from the loop above), or some tile carries an
    # explicit non-default weight (auto-added here). Either way, once the
    # layer exists it must be FULLY populated (every terrain-bearing tile
    # gets a float — its explicit weight or the 1.0 default) so the audit
    # never reads an unpopulated/garbage value off a declared-but-untouched
    # layer. Only when NEITHER condition holds do we add no layer at all, so
    # a plain unweighted config's .tres stays byte-for-byte unchanged.
    any_weight = any(
        _resolve_assign_weights(asn, tuple(asn.get("origin", [0, 0])))
        for asn in cfg.get("terrain_assign") or []
    )
    weight_layer_index = -1
    for i, cd in enumerate(plan["custom_data"]):
        if cd["name"] == _WEIGHT_LAYER_NAME:
            weight_layer_index = i
            break
    if weight_layer_index == -1 and any_weight:
        weight_layer_index = len(plan["custom_data"])
        plan["custom_data"].append({"name": _WEIGHT_LAYER_NAME, "type": "TYPE_FLOAT"})
    plan["weight_layer_index"] = weight_layer_index

    for ti, tset in enumerate(cfg.get("terrain_set") or []):
        mode = tset.get("mode", "match_corners_and_sides").upper()
        terrains = tset.get("terrains") or []
        plan["terrain_sets"].append(
            {
                "mode": "TERRAIN_MODE_" + mode,
                "terrains": [{"name": t["name"], "color": t.get("color", "#ffffff")} for t in terrains],
            }
        )
        for terr_idx, t in enumerate(terrains):
            plan["terrain_index"][t["name"]] = [ti, terr_idx]

    # Index terrain_assign + animation by atlas id.
    assigns_by_atlas: dict[str, list[dict]] = {}
    for asn in cfg.get("terrain_assign") or []:
        assigns_by_atlas.setdefault(asn["atlas"], []).append(asn)
    anims_by_atlas: dict[str, list[dict]] = {}
    for an in cfg.get("animation") or []:
        anims_by_atlas.setdefault(an["atlas"], []).append(an)

    for a in cfg["atlas"]:
        aid = a["id"]
        atlas_plan: dict = {
            "id": aid,
            "texture": a["texture"],
            "margins": a.get("margins", [0, 0]),
            "separation": a.get("separation", [0, 0]),
            "scan": a.get("scan", "non_transparent"),
            "explicit_tiles": [list(t["coords"]) for t in (a.get("tiles") or [])],
            "animations": [],
            "assign": {},  # "x,y" -> {terrain, bits}
        }

        # Animation groups: enumerate BASE regions (frame 0) + all reserved
        # frame regions. Frame regions consume real atlas grid space and are
        # never registered as separate tiles.
        for an in anims_by_atlas.get(aid, []):
            (bx0, by0), (bx1, by1) = an["base_region"]
            fx, fy = an.get("frame_offset", [1, 0])
            frames = an["frames"]
            base_cells = []
            reserved = []
            for by in range(by0, by1 + 1):
                for bx in range(bx0, bx1 + 1):
                    base_cells.append([bx, by])
                    for f in range(1, frames):
                        reserved.append([bx + f * fx, by + f * fy])
            # Godot lays animation frames out left-to-right, top-to-bottom in a
            # rectangle of `columns` width, contiguous from the base coords, so
            # set_tile_animation_columns must MATCH the reserved layout: a
            # horizontal strip (frame_offset [1,0]) => columns = frames; a
            # vertical strip (frame_offset [0,1]) => columns = 1. The contiguity
            # rule itself (offset must be [1,0] or [0,1]) is validated ONCE in
            # validate_config — this is the single source of truth (P1 review
            # carry-in); by the time a cfg reaches this function it has already
            # passed that check, so only the vertical case needs branching here.
            columns = 1 if (fx == 0 and fy == 1) else frames
            atlas_plan["animations"].append(
                {
                    "base_cells": base_cells,
                    "reserved": reserved,
                    "frames": frames,
                    "columns": columns,
                    "duration": an.get("duration", 1.0),
                    "mode": "TILE_ANIMATION_MODE_DEFAULT" if an.get("mode", "default") == "default" else "TILE_ANIMATION_MODE_RANDOM_START_TIMES",
                }
            )

        # Terrain assignments -> per-cell {terrain, bits, weight}. `weight` is
        # baked only when the weight layer is active (weight_layer_index >= 0),
        # in which case EVERY terrain-bearing tile gets a float — its explicit
        # weight, or _DEFAULT_WEIGHT — so the layer is fully populated and the
        # audit reads a real value off every variant.
        for asn in assigns_by_atlas.get(aid, []):
            terr = asn["terrain"]
            origin = tuple(asn.get("origin", [0, 0]))
            bits_by_coords = _resolve_assign_bits(asn, origin)
            weight_by_coords = _resolve_assign_weights(asn, origin)
            for (cx, cy), bits in bits_by_coords.items():
                cell_assign: dict = {"terrain": terr, "bits": bits}
                if weight_layer_index >= 0:
                    cell_assign["weight"] = weight_by_coords.get((cx, cy), _DEFAULT_WEIGHT)
                atlas_plan["assign"][f"{cx},{cy}"] = cell_assign

        plan["atlases"].append(atlas_plan)

    plan_json = json.dumps(plan)

    # The GDScript. Kept as a here-doc; the plan JSON is injected as a string
    # literal and parsed with JSON.parse_string inside the script.
    return f'''extends SceneTree

const PLAN_JSON := {json.dumps(plan_json)}
const OUT_PATH := {json.dumps(out_path_res)}

func _initialize() -> void:
\tvar warnings: Array = []
\tvar report: Dictionary = _build(warnings)
\treport["warnings"] = warnings
\tprint("{begin}")
\tprint(JSON.stringify(report))
\tprint("{end}")
\tquit(0)

func _cell_key(x: int, y: int) -> String:
\treturn str(x) + "," + str(y)

func _build(warnings: Array) -> Dictionary:
\tvar plan: Dictionary = JSON.parse_string(PLAN_JSON)
\tif plan == null:
\t\treturn {{"ok": false, "error": "internal: plan JSON did not parse"}}

\tvar tile_size := Vector2i(int(plan["tile_size"][0]), int(plan["tile_size"][1]))
\tvar tileset := TileSet.new()
\ttileset.tile_size = tile_size

\t# --- custom-data layers (before tiles reference them) ---
\tfor i in range((plan["custom_data"] as Array).size()):
\t\tvar cd: Dictionary = plan["custom_data"][i]
\t\ttileset.add_custom_data_layer(i)
\t\ttileset.set_custom_data_layer_name(i, cd["name"])
\t\ttileset.set_custom_data_layer_type(i, _variant_type(cd["type"]))

\t# --- physics + navigation layers (P1-review carry-in: conditional on the
\t# config actually declaring collision/navigation, so a plain tileset doesn't
\t# carry an empty nav layer or an unused physics layer) ---
\tif bool(plan.get("has_physics", false)):
\t\ttileset.add_physics_layer(0)
\tif bool(plan.get("has_navigation", false)):
\t\ttileset.add_navigation_layer(0)

\t# --- terrain sets + terrains (terrain_set must exist before any tile sets terrain) ---
\tfor ti in range((plan["terrain_sets"] as Array).size()):
\t\tvar tset: Dictionary = plan["terrain_sets"][ti]
\t\ttileset.add_terrain_set(ti)
\t\ttileset.set_terrain_set_mode(ti, _terrain_mode(tset["mode"]))
\t\tvar terrains: Array = tset["terrains"]
\t\tfor tj in range(terrains.size()):
\t\t\ttileset.add_terrain(ti, tj)
\t\t\ttileset.set_terrain_name(ti, tj, terrains[tj]["name"])
\t\t\ttileset.set_terrain_color(ti, tj, _color(terrains[tj]["color"]))

\tvar terrain_index: Dictionary = plan["terrain_index"]
\tvar full_square: Array = plan["physics_full_square"]
\t# -1 when no tile carries an explicit weight (no `weight` layer baked); else
\t# the custom-data layer index the per-tile weight float is written into.
\tvar weight_layer_index := int(plan.get("weight_layer_index", -1))

\tvar atlas_report: Array = []
\tvar total_tiles := 0
\tvar total_animated := 0
\tvar total_bits := 0
\tvar total_skipped := 0

\tfor atlas_plan in plan["atlases"]:
\t\tvar tex_path: String = atlas_plan["texture"]
\t\tvar tex := _load_texture(tex_path)
\t\tif tex == null:
\t\t\treturn {{"ok": false, "error": "could not load atlas texture: " + tex_path}}

\t\tvar src := TileSetAtlasSource.new()
\t\tsrc.texture = tex
\t\tsrc.texture_region_size = tile_size
\t\tsrc.margins = Vector2i(int(atlas_plan["margins"][0]), int(atlas_plan["margins"][1]))
\t\tsrc.separation = Vector2i(int(atlas_plan["separation"][0]), int(atlas_plan["separation"][1]))

\t\tvar img := tex.get_image()
\t\tvar grid_w := 0
\t\tvar grid_h := 0
\t\tif img != null:
\t\t\t# N tiles at `separation` apart span N*tile + (N-1)*separation pixels, so
\t\t\t# adding one extra `separation` allowance before dividing accounts for
\t\t\t# the fencepost the naive (image - margin) / (tile + separation) formula
\t\t\t# drops on the FINAL tile (undercounts by one column/row whenever
\t\t\t# separation is nonzero — P1-hardening finding #3).
\t\t\tgrid_w = int(floor(float(img.get_width() - src.margins.x + src.separation.x) / float(tile_size.x + src.separation.x)))
\t\t\tgrid_h = int(floor(float(img.get_height() - src.margins.y + src.separation.y) / float(tile_size.y + src.separation.y)))

\t\t# 1) RESERVE animation frame regions FIRST — they consume grid space and
\t\t#    must never be scanned/created as standalone tiles.
\t\tvar reserved := {{}}
\t\tvar base_cells := {{}}   # "x,y" -> animation dict for that base cell
\t\tfor anim in atlas_plan["animations"]:
\t\t\tfor rc in anim["reserved"]:
\t\t\t\treserved[_cell_key(int(rc[0]), int(rc[1]))] = true
\t\t\tfor bc in anim["base_cells"]:
\t\t\t\tbase_cells[_cell_key(int(bc[0]), int(bc[1]))] = anim

\t\t# 2) Collect base cells to create: explicit list, or scan.
\t\tvar cells_to_make: Array = []
\t\tif atlas_plan["scan"] == "explicit":
\t\t\tfor c in atlas_plan["explicit_tiles"]:
\t\t\t\tcells_to_make.append(Vector2i(int(c[0]), int(c[1])))
\t\telse:
\t\t\tvar scan_all: bool = atlas_plan["scan"] == "all"
\t\t\tfor gy in range(grid_h):
\t\t\t\tfor gx in range(grid_w):
\t\t\t\t\tvar key := _cell_key(gx, gy)
\t\t\t\t\tif reserved.has(key):
\t\t\t\t\t\tcontinue
\t\t\t\t\tif scan_all or _cell_has_pixels(img, gx, gy, tile_size, src.margins, src.separation):
\t\t\t\t\t\tcells_to_make.append(Vector2i(gx, gy))
\t\t\t\t\telse:
\t\t\t\t\t\ttotal_skipped += 1

\t\t# Always include animation base cells (a base cell may be transparent at
\t\t# frame 0 sampling but is a real animated tile).
\t\tfor bk in base_cells.keys():
\t\t\tvar parts: PackedStringArray = bk.split(",")
\t\t\tvar bcoords := Vector2i(int(parts[0]), int(parts[1]))
\t\t\tif not cells_to_make.has(bcoords):
\t\t\t\tcells_to_make.append(bcoords)

\t\t# 3) create_tile per base cell + animation setup for animated bases.
\t\tvar made := 0
\t\tvar animated := 0
\t\tfor coords in cells_to_make:
\t\t\tif not src.has_room_for_tile(coords, Vector2i.ONE, 1, Vector2i.ZERO, 1, Vector2i(-1, -1)):
\t\t\t\twarnings.append("no room for tile at " + str(coords) + " in atlas " + str(atlas_plan["id"]))
\t\t\t\tcontinue
\t\t\tsrc.create_tile(coords)
\t\t\tmade += 1
\t\t\tvar bk := _cell_key(coords.x, coords.y)
\t\t\tif base_cells.has(bk):
\t\t\t\tvar anim: Dictionary = base_cells[bk]
\t\t\t\tsrc.set_tile_animation_columns(coords, int(anim["columns"]))
\t\t\t\tsrc.set_tile_animation_frames_count(coords, int(anim["frames"]))
\t\t\t\tsrc.set_tile_animation_mode(coords, _anim_mode(anim["mode"]))
\t\t\t\tfor f in range(int(anim["frames"])):
\t\t\t\t\tsrc.set_tile_animation_frame_duration(coords, f, float(anim["duration"]))
\t\t\t\tanimated += 1

\t\tvar source_id := tileset.add_source(src)

\t\t# 4) Per-tile data: terrain_set FIRST, then terrain, then peering bits,
\t\t#    then collision + custom data.
\t\tvar assign: Dictionary = atlas_plan["assign"]
\t\tvar bits_assigned := 0
\t\tfor coords in cells_to_make:
\t\t\tif not src.has_tile(coords):
\t\t\t\tcontinue
\t\t\tvar td := src.get_tile_data(coords, 0)
\t\t\tif td == null:
\t\t\t\tcontinue
\t\t\tvar akey := _cell_key(coords.x, coords.y)
\t\t\tif assign.has(akey):
\t\t\t\tvar a: Dictionary = assign[akey]
\t\t\t\tvar tname: String = a["terrain"]
\t\t\t\tif terrain_index.has(tname):
\t\t\t\t\tvar idx: Array = terrain_index[tname]
\t\t\t\t\ttd.terrain_set = int(idx[0])
\t\t\t\t\ttd.terrain = int(idx[1])
\t\t\t\t\tfor bit_name in a["bits"]:
\t\t\t\t\t\tvar bit := _cell_neighbor(bit_name)
\t\t\t\t\t\tif bit >= 0:
\t\t\t\t\t\t\ttd.set_terrain_peering_bit(bit, int(idx[1]))
\t\t\t\t\t\t\tbits_assigned += 1
\t\t\t\t\tif full_square.has(tname):
\t\t\t\t\t\t_add_full_square_collision(td, tile_size)
\t\t\t\t\t# Bake the per-variant weight into the `weight` custom-data layer
\t\t\t\t\t# (float; every terrain-bearing tile carries one when the layer is
\t\t\t\t\t# active, defaulting to 1.0). This is what the audit reads back.
\t\t\t\t\tif weight_layer_index >= 0 and a.has("weight"):
\t\t\t\t\t\ttd.set_custom_data_by_layer_id(weight_layer_index, float(a["weight"]))

\t\ttotal_tiles += made
\t\ttotal_animated += animated
\t\ttotal_bits += bits_assigned
\t\tatlas_report.append({{
\t\t\t"id": atlas_plan["id"],
\t\t\t"source_id": source_id,
\t\t\t"tiles": made,
\t\t\t"animated_groups": animated,
\t\t\t"reserved_frame_regions": reserved.size(),
\t\t\t"bits_assigned": bits_assigned,
\t\t}})

\t# --- save (ensure the out dir exists first) ---
\tvar out_dir := OUT_PATH.get_base_dir()
\tif out_dir != "" and not DirAccess.dir_exists_absolute(out_dir):
\t\tDirAccess.make_dir_recursive_absolute(out_dir)
\tvar save_err := ResourceSaver.save(tileset, OUT_PATH)
\tif save_err != OK:
\t\treturn {{"ok": false, "error": "ResourceSaver.save failed: " + str(save_err)}}

\t# --- reload sanity check ---
\tvar reloaded := ResourceLoader.load(OUT_PATH, "TileSet", ResourceLoader.CACHE_MODE_IGNORE) as TileSet
\tif reloaded == null:
\t\treturn {{"ok": false, "error": "reload failed: ResourceLoader.load returned null for " + OUT_PATH}}
\tvar reload_tiles := 0
\tfor si in range(reloaded.get_source_count()):
\t\tvar rsid := reloaded.get_source_id(si)
\t\tvar rsrc := reloaded.get_source(rsid) as TileSetAtlasSource
\t\tif rsrc != null:
\t\t\treload_tiles += rsrc.get_tiles_count()

\treturn {{
\t\t"ok": true,
\t\t"out_path": OUT_PATH,
\t\t"tile_size": [tile_size.x, tile_size.y],
\t\t"total_tiles": total_tiles,
\t\t"total_animated_groups": total_animated,
\t\t"total_bits_assigned": total_bits,
\t\t"skipped_transparent": total_skipped,
\t\t"terrain_sets": (plan["terrain_sets"] as Array).size(),
\t\t"custom_data_layers": (plan["custom_data"] as Array).size(),
\t\t"atlases": atlas_report,
\t\t"reload_source_count": reloaded.get_source_count(),
\t\t"reload_tile_count": reload_tiles,
\t}}

# Load an atlas texture robustly. Prefer ResourceLoader (works for already-
# imported project sheets, preserving their import settings). Fall back to
# reading the raw PNG/image bytes off disk via Image.load — this is what makes a
# freshly-authored, never-imported sheet (or a headless CI fixture with no
# .godot/imported cache) work, since the resource importer has not run.
func _load_texture(tex_path: String) -> Texture2D:
\tif ResourceLoader.exists(tex_path):
\t\tvar res := ResourceLoader.load(tex_path) as Texture2D
\t\tif res != null:
\t\t\treturn res
\tvar abs_path := ProjectSettings.globalize_path(tex_path)
\tvar img := Image.new()
\tif img.load(abs_path) != OK:
\t\treturn null
\treturn ImageTexture.create_from_image(img)

func _cell_has_pixels(img: Image, gx: int, gy: int, tile_size: Vector2i, margins: Vector2i, sep: Vector2i) -> bool:
\tif img == null:
\t\treturn true
\tvar ox := margins.x + gx * (tile_size.x + sep.x)
\tvar oy := margins.y + gy * (tile_size.y + sep.y)
\tfor py in range(tile_size.y):
\t\tfor px in range(tile_size.x):
\t\t\tvar sx := ox + px
\t\t\tvar sy := oy + py
\t\t\tif sx < 0 or sy < 0 or sx >= img.get_width() or sy >= img.get_height():
\t\t\t\tcontinue
\t\t\tif img.get_pixel(sx, sy).a > 0.0:
\t\t\t\treturn true
\treturn false

func _add_full_square_collision(td: TileData, tile_size: Vector2i) -> void:
\ttd.add_collision_polygon(0)
\tvar hx := float(tile_size.x) / 2.0
\tvar hy := float(tile_size.y) / 2.0
\tvar poly := PackedVector2Array([
\t\tVector2(-hx, -hy), Vector2(hx, -hy), Vector2(hx, hy), Vector2(-hx, hy)
\t])
\ttd.set_collision_polygon_points(0, 0, poly)

func _variant_type(name: String) -> int:
\tmatch name:
\t\t"TYPE_STRING": return TYPE_STRING
\t\t"TYPE_INT": return TYPE_INT
\t\t"TYPE_FLOAT": return TYPE_FLOAT
\t\t"TYPE_BOOL": return TYPE_BOOL
\treturn TYPE_STRING

func _terrain_mode(name: String) -> int:
\tmatch name:
\t\t"TERRAIN_MODE_MATCH_CORNERS_AND_SIDES": return TileSet.TERRAIN_MODE_MATCH_CORNERS_AND_SIDES
\t\t"TERRAIN_MODE_MATCH_CORNERS": return TileSet.TERRAIN_MODE_MATCH_CORNERS
\t\t"TERRAIN_MODE_MATCH_SIDES": return TileSet.TERRAIN_MODE_MATCH_SIDES
\treturn TileSet.TERRAIN_MODE_MATCH_CORNERS_AND_SIDES

func _anim_mode(name: String) -> int:
\tif name == "TILE_ANIMATION_MODE_RANDOM_START_TIMES":
\t\treturn TileSetAtlasSource.TILE_ANIMATION_MODE_RANDOM_START_TIMES
\treturn TileSetAtlasSource.TILE_ANIMATION_MODE_DEFAULT

func _color(hexcode: String) -> Color:
\treturn Color.html(hexcode)

# Map our compass bit names to TileSet.CellNeighbor enum values. NOTE: the
# built-in terrain solver (#76493 wrong-terrain, #89844 ignored diagonal bits;
# both open on 4.6.2 + 4.7-stable as of 2026-07-03) is deliberately NOT used —
# these bits are read by the in-house matcher. Re-audit by grepping the issue
# numbers on any engine bump.
func _cell_neighbor(name: String) -> int:
\tmatch name:
\t\t"TOP_SIDE": return TileSet.CELL_NEIGHBOR_TOP_SIDE
\t\t"RIGHT_SIDE": return TileSet.CELL_NEIGHBOR_RIGHT_SIDE
\t\t"BOTTOM_SIDE": return TileSet.CELL_NEIGHBOR_BOTTOM_SIDE
\t\t"LEFT_SIDE": return TileSet.CELL_NEIGHBOR_LEFT_SIDE
\t\t"TOP_RIGHT_CORNER": return TileSet.CELL_NEIGHBOR_TOP_RIGHT_CORNER
\t\t"BOTTOM_RIGHT_CORNER": return TileSet.CELL_NEIGHBOR_BOTTOM_RIGHT_CORNER
\t\t"BOTTOM_LEFT_CORNER": return TileSet.CELL_NEIGHBOR_BOTTOM_LEFT_CORNER
\t\t"TOP_LEFT_CORNER": return TileSet.CELL_NEIGHBOR_TOP_LEFT_CORNER
\t\t"TOP_CORNER": return TileSet.CELL_NEIGHBOR_TOP_CORNER
\t\t"RIGHT_CORNER": return TileSet.CELL_NEIGHBOR_RIGHT_CORNER
\t\t"BOTTOM_CORNER": return TileSet.CELL_NEIGHBOR_BOTTOM_CORNER
\t\t"LEFT_CORNER": return TileSet.CELL_NEIGHBOR_LEFT_CORNER
\treturn -1
'''


# ---------------------------------------------------------------------------
# Tool entry point
# ---------------------------------------------------------------------------


def _summarize(report: dict, out_path: str) -> str:
    if not report.get("ok"):
        return f"ERROR — tileset_build: {report.get('error', 'unknown build error')}"
    lines = [
        f"OK  TileSet built: {out_path}",
        f"  tile size: {report['tile_size'][0]}x{report['tile_size'][1]}",
        f"  tiles: {report['total_tiles']}  animated groups: {report['total_animated_groups']}  "
        f"peering bits: {report['total_bits_assigned']}  skipped transparent: {report['skipped_transparent']}",
        f"  terrain sets: {report['terrain_sets']}  custom-data layers: {report['custom_data_layers']}",
    ]
    for a in report.get("atlases", []):
        lines.append(
            f"  atlas {a['id']} (src {a['source_id']}): {a['tiles']} tiles, "
            f"{a['animated_groups']} animated, {a['reserved_frame_regions']} reserved frame regions, "
            f"{a['bits_assigned']} bits"
        )
    lines.append(
        f"  reload check: {report['reload_tile_count']} tiles across {report['reload_source_count']} source(s)"
    )
    warns = report.get("warnings") or []
    if warns:
        lines.append(f"  warnings ({len(warns)}):")
        for w in warns[:20]:
            lines.append(f"    - {w}")
    lines.append("  Manual pass worth doing: open the .tres in the Godot editor once against the real sheet to eyeball edges/animation.")
    return "\n".join(lines)


def tileset_build(config_path: str, out_path: str, timeout: int = 180) -> str:
    """Build a `.tres` TileSet from a declarative TOML/JSON config, headless.

    The config format is chosen by `config_path`'s extension (.json → JSON,
    otherwise TOML); both parse to the same validated schema. Validates the
    config in Python (water-bottom law: <=1 terrain per terrain
    set; animated tiles whose cells carry a terrain must be mode='default'), composes ONE
    GDScript, parse-checks it, runs it via the shared headless probe, parses the
    nonce'd JSON report, and returns a human-readable summary. Never raises —
    config/build errors come back as structured report strings.
    """
    try:
        cfg = load_config(config_path)
    except ConfigError as e:
        return f"ERROR — invalid config: {e}"

    # Resolve out_path into the project (write only to declared out paths).
    try:
        out_abs = config.resolve_project_path(out_path)
    except config.PathEscapeError:
        return f"Refused: {out_path} resolves outside the project root."
    if out_path.startswith("res://"):
        out_res = out_path
    else:
        root = config.PROJECT_ROOT.resolve()
        out_res = "res://" + out_abs.resolve().relative_to(root).as_posix()

    nonce, _, _ = make_sentinels()
    try:
        source = compose_build_script(cfg, out_res, nonce)
    except ConfigError as e:
        return f"ERROR — invalid config: {e}"

    # Parse-check the composed GDScript before running (existing mcp discipline).
    parse_err = _parse_check(source)
    if parse_err:
        return f"ERROR — composed build script did not parse:\n{parse_err}"

    r = runner.run_temp_probe(source, timeout=timeout)
    if r.get("timeout"):
        return f"UNAVAILABLE — tileset_build timed out after {timeout}s (Godot may be unavailable or the sheet is very large)."
    if r.get("rc") is None:
        return f"UNAVAILABLE — {r.get('err') or 'tileset_build could not launch Godot.'}"

    out = r.get("out") or ""
    payload, reason = parse_sentinel_json(out, nonce)
    if payload is None:
        tail = (r.get("err") or out).strip()
        return f"UNAVAILABLE — tileset_build produced no parseable report ({reason}).\n{tail[-800:]}"
    return _summarize(payload, out_res)


def _parse_check(source: str) -> str:
    """Parse-check a composed GDScript via a temp file + --check-only.

    Returns "" on success, or an error message. Reuses runner._run so binary
    resolution/timeouts match the rest of the server.
    """
    import os
    import tempfile

    fd, gd_path = tempfile.mkstemp(suffix=".gd", prefix="godot_mcp_procgen_check_")
    try:
        try:
            os.write(fd, source.encode("utf-8"))
        finally:
            os.close(fd)
        r = runner._run(["--check-only", "--script", gd_path], timeout=60)
    finally:
        runner._safe_unlink(gd_path)
        runner._safe_unlink(gd_path + ".uid")

    if r.get("timeout"):
        return ""  # can't parse-check offline; let the real run surface it
    if r.get("rc") is None:
        return ""  # Godot unavailable; real run will report UNAVAILABLE
    if r["rc"] == 0 and not (r.get("err") or "").strip():
        return ""
    msg = ((r.get("err") or "") + "\n" + (r.get("out") or "")).strip()
    return msg[-2000:]


# ---------------------------------------------------------------------------
# terrain_audit (Phase 2)
# ---------------------------------------------------------------------------
#
# GDScript loads the .tres and dumps RAW per-tile facts only (terrain_set,
# terrain, which of the 8 known peering bits are valid + set-to-self, and
# animation frames/duration/mode). ALL interpretation — expected-signature
# computation, coverage/missing/duplicate classification, law violations,
# unused-tile detection, animation-sync linting — happens in Python against
# that raw dump, so the "what does clean look like" logic lives in one place
# (testable without Godot) and stays in sync with expected_signature_set().


def compose_audit_script(tileset_path_res: str, nonce: str) -> str:
    """Compose the GDScript that loads *tileset_path_res* and dumps raw
    per-terrain-set-mode, per-tile terrain/peering-bit/animation facts.

    Dumps EVERY tile across every source (alt 0 only, per the project's
    verified-facts note that alt 0 is the main tile), not just those in a
    single requested terrain_set — filtering by terrain_set happens in Python
    (`_audit_report`) so the raw dump is reusable for any requested scope
    without re-running Godot.
    """
    begin = f"{_SENTINEL_BEGIN}:{nonce}"
    end = f"{_SENTINEL_END}:{nonce}"
    bit_names_gd = json.dumps(list(_ALL_BIT_NAMES))

    return f'''extends SceneTree

const TILESET_PATH := {json.dumps(tileset_path_res)}
const BIT_NAMES: Array = {bit_names_gd}

func _initialize() -> void:
\tvar report: Dictionary = _dump()
\tprint("{begin}")
\tprint(JSON.stringify(report))
\tprint("{end}")
\tquit(0)

func _dump() -> Dictionary:
\tvar ts := ResourceLoader.load(TILESET_PATH, "TileSet", ResourceLoader.CACHE_MODE_IGNORE) as TileSet
\tif ts == null:
\t\treturn {{"ok": false, "error": "could not load TileSet at " + TILESET_PATH}}

\tvar terrain_sets: Array = []
\tfor tsi in range(ts.get_terrain_sets_count()):
\t\tvar terrains: Array = []
\t\tfor terr_i in range(ts.get_terrains_count(tsi)):
\t\t\tterrains.append({{"index": terr_i, "name": ts.get_terrain_name(tsi, terr_i)}})
\t\tterrain_sets.append({{
\t\t\t"index": tsi,
\t\t\t"mode": _mode_name(ts.get_terrain_set_mode(tsi)),
\t\t\t"terrains": terrains,
\t\t}})

\t# Locate the `weight` custom-data layer once (index, or -1 if the tileset
\t# has no weights baked). The per-tile weight rides this layer.
\tvar weight_layer := -1
\tfor cdi in range(ts.get_custom_data_layers_count()):
\t\tif ts.get_custom_data_layer_name(cdi) == {json.dumps(_WEIGHT_LAYER_NAME)}:
\t\t\tweight_layer = cdi
\t\t\tbreak

\tvar tiles: Array = []
\tfor si in range(ts.get_source_count()):
\t\tvar sid := ts.get_source_id(si)
\t\tvar src := ts.get_source(sid) as TileSetAtlasSource
\t\tif src == null:
\t\t\tcontinue
\t\tfor ti in range(src.get_tiles_count()):
\t\t\tvar coords := src.get_tile_id(ti)
\t\t\tvar td := src.get_tile_data(coords, 0)
\t\t\tif td == null:
\t\t\t\tcontinue
\t\t\tvar set_bits: Array = []
\t\t\tfor bn in BIT_NAMES:
\t\t\t\tvar bit := _cell_neighbor(bn)
\t\t\t\tif bit < 0:
\t\t\t\t\tcontinue
\t\t\t\tif not td.is_valid_terrain_peering_bit(bit):
\t\t\t\t\tcontinue
\t\t\t\tif td.get_terrain_peering_bit(bit) == td.terrain:
\t\t\t\t\tset_bits.append(bn)
\t\t\tvar custom_data_present := false
\t\t\tfor cdi in range(ts.get_custom_data_layers_count()):
\t\t\t\tvar v = td.get_custom_data_by_layer_id(cdi)
\t\t\t\tif _is_present_value(v):
\t\t\t\t\tcustom_data_present = true
\t\t\t\t\tbreak
\t\t\t# Per-tile weight off the `weight` layer; default 1.0 when no such layer
\t\t\t# (unweighted tileset) so the matcher always reads a usable relative weight.
\t\t\tvar weight := 1.0
\t\t\tif weight_layer >= 0:
\t\t\t\tweight = float(td.get_custom_data_by_layer_id(weight_layer))
\t\t\tvar frames := src.get_tile_animation_frames_count(coords)
\t\t\tvar anim = null
\t\t\tif frames > 1:
\t\t\t\tvar durations: Array = []
\t\t\t\tfor f in range(frames):
\t\t\t\t\tdurations.append(src.get_tile_animation_frame_duration(coords, f))
\t\t\t\tanim = {{
\t\t\t\t\t"frames": frames,
\t\t\t\t\t"durations": durations,
\t\t\t\t\t"mode": _anim_mode_name(src.get_tile_animation_mode(coords)),
\t\t\t\t}}
\t\t\ttiles.append({{
\t\t\t\t"source_id": sid,
\t\t\t\t"coords": [coords.x, coords.y],
\t\t\t\t"terrain_set": td.terrain_set,
\t\t\t\t"terrain": td.terrain,
\t\t\t\t"bits": set_bits,
\t\t\t\t"custom_data": custom_data_present,
\t\t\t\t"weight": weight,
\t\t\t\t"animation": anim,
\t\t\t}})

\treturn {{
\t\t"ok": true,
\t\t"terrain_sets": terrain_sets,
\t\t"tiles": tiles,
\t}}

func _mode_name(mode: int) -> String:
\tmatch mode:
\t\tTileSet.TERRAIN_MODE_MATCH_CORNERS_AND_SIDES: return "MATCH_CORNERS_AND_SIDES"
\t\tTileSet.TERRAIN_MODE_MATCH_CORNERS: return "MATCH_CORNERS"
\t\tTileSet.TERRAIN_MODE_MATCH_SIDES: return "MATCH_SIDES"
\treturn "UNKNOWN"

func _anim_mode_name(mode: int) -> String:
\tif mode == TileSetAtlasSource.TILE_ANIMATION_MODE_RANDOM_START_TIMES:
\t\treturn "RANDOM_START_TIMES"
\treturn "DEFAULT"

# Is a custom-data value non-default (i.e. "present")? Type-dispatched so a
# float layer (e.g. the `weight` layer) never hits a String/int comparison,
# which GDScript rejects as invalid operands across types.
func _is_present_value(v: Variant) -> bool:
\tmatch typeof(v):
\t\tTYPE_NIL: return false
\t\tTYPE_STRING, TYPE_STRING_NAME: return String(v) != ""
\t\tTYPE_INT: return int(v) != 0
\t\tTYPE_FLOAT: return float(v) != 0.0
\t\tTYPE_BOOL: return bool(v)
\treturn true

# Same compass-name -> CellNeighbor mapping as the build script (kept in sync
# by hand; both are static engine-enum tables, not generated from each other).
func _cell_neighbor(name: String) -> int:
\tmatch name:
\t\t"TOP_SIDE": return TileSet.CELL_NEIGHBOR_TOP_SIDE
\t\t"RIGHT_SIDE": return TileSet.CELL_NEIGHBOR_RIGHT_SIDE
\t\t"BOTTOM_SIDE": return TileSet.CELL_NEIGHBOR_BOTTOM_SIDE
\t\t"LEFT_SIDE": return TileSet.CELL_NEIGHBOR_LEFT_SIDE
\t\t"TOP_RIGHT_CORNER": return TileSet.CELL_NEIGHBOR_TOP_RIGHT_CORNER
\t\t"BOTTOM_RIGHT_CORNER": return TileSet.CELL_NEIGHBOR_BOTTOM_RIGHT_CORNER
\t\t"BOTTOM_LEFT_CORNER": return TileSet.CELL_NEIGHBOR_BOTTOM_LEFT_CORNER
\t\t"TOP_LEFT_CORNER": return TileSet.CELL_NEIGHBOR_TOP_LEFT_CORNER
\t\t"TOP_CORNER": return TileSet.CELL_NEIGHBOR_TOP_CORNER
\t\t"RIGHT_CORNER": return TileSet.CELL_NEIGHBOR_RIGHT_CORNER
\t\t"BOTTOM_CORNER": return TileSet.CELL_NEIGHBOR_BOTTOM_CORNER
\t\t"LEFT_CORNER": return TileSet.CELL_NEIGHBOR_LEFT_CORNER
\treturn -1
'''


def _sig_key(bits: list[str]) -> str:
    """Canonical signature key: comma-joined, sorted bit names ("" = the
    isolated/no-neighbor signature). Shared by coverage-dict keys and the
    expected-signature lookup so both sides compare identically."""
    return ",".join(sorted(bits))


def _audit_report(dump: dict, terrain_set: int) -> dict:
    """Build the terrain_audit report (human table + machine `coverage` dict)
    from the raw GDScript dump. See `terrain_audit`'s docstring for the
    `coverage` dict's documented shape — this is the one function that
    constructs it, so that docstring and this code must be kept in sync.
    """
    if not dump.get("ok"):
        return {"ok": False, "error": dump.get("error", "unknown audit error")}

    all_terrain_sets: list[dict] = dump.get("terrain_sets", [])
    all_tiles: list[dict] = dump.get("tiles", [])

    scoped_sets = all_terrain_sets if terrain_set == -1 else [ts for ts in all_terrain_sets if ts["index"] == terrain_set]
    if terrain_set != -1 and not scoped_sets:
        return {"ok": False, "error": f"terrain_set {terrain_set} does not exist (tileset has {len(all_terrain_sets)})"}
    scoped_indices = {ts["index"] for ts in scoped_sets}

    errors: list[str] = []
    warnings: list[str] = []
    coverage: dict[str, dict] = {}

    # Law violation: more than one terrain in a terrain set. Tileset-wide,
    # NOT scoped — a violation in a different terrain_set than the one the
    # caller asked to focus on is still a real data-integrity problem.
    for ts in all_terrain_sets:
        if len(ts["terrains"]) > 1:
            names = ", ".join(t["name"] for t in ts["terrains"])
            errors.append(
                f"terrain_set {ts['index']}: {len(ts['terrains'])} terrains ({names}) — "
                "water-bottom law violation, at most ONE terrain per terrain set is allowed"
            )

    # Broken ordering: terrain != -1 but terrain_set == -1, anywhere in the
    # tileset (this is a per-tile data-corruption check, not scoped to the
    # requested terrain_set — a broken tile has no valid terrain_set to scope by).
    broken_ordering: list[dict] = []
    for t in all_tiles:
        if t["terrain"] != -1 and t["terrain_set"] == -1:
            broken_ordering.append({"source_id": t["source_id"], "coords": t["coords"]})
    if broken_ordering:
        errors.append(
            f"{len(broken_ordering)} tile(s) have terrain != -1 but terrain_set == -1 (broken ordering — "
            "terrain_set must be assigned before terrain): "
            + ", ".join(f"src {b['source_id']} {tuple(b['coords'])}" for b in broken_ordering[:10])
        )

    # Animation sync lint: every animated tile belonging to a terrain (any
    # terrain_set, any terrain index >= 0) must share identical frames/
    # duration and mode == DEFAULT. Scoped to tiles inside the requested
    # terrain_set(s) when the caller narrowed the audit.
    animated_terrain_tiles = [
        t for t in all_tiles
        if t.get("animation") is not None and t["terrain"] != -1 and t["terrain_set"] in scoped_indices
    ]
    if animated_terrain_tiles:
        first = animated_terrain_tiles[0]["animation"]
        baseline = (first["frames"], tuple(first["durations"]), first["mode"])
        desynced = [
            t for t in animated_terrain_tiles
            if (t["animation"]["frames"], tuple(t["animation"]["durations"]), t["animation"]["mode"]) != baseline
        ]
        non_default = [t for t in animated_terrain_tiles if t["animation"]["mode"] != "DEFAULT"]
        if desynced or non_default:
            bad = {(t["source_id"], tuple(t["coords"])) for t in (desynced + non_default)}
            errors.append(
                f"{len(bad)} animated terrain tile(s) desync from the baseline "
                f"(frames={baseline[0]}, durations={list(baseline[1])}, mode={baseline[2]}) — every water-bearing "
                "animated tile must share identical frames/duration and mode=DEFAULT, or coastlines fall out of "
                "phase: " + ", ".join(f"src {sid} {coords}" for sid, coords in sorted(bad)[:10])
            )

    # Per-terrain-set signature coverage.
    for ts in scoped_sets:
        tsi = ts["index"]
        mode = ts["mode"]
        terrain_names = {t["index"]: t["name"] for t in ts["terrains"]}
        try:
            expected = expected_signature_set(mode)
        except ValueError as e:
            errors.append(f"terrain_set {tsi}: {e}")
            continue

        tiles_in_set = [t for t in all_tiles if t["terrain_set"] == tsi and t["terrain"] != -1]
        by_sig: dict[str, list[dict]] = {}
        for t in tiles_in_set:
            key = _sig_key(t["bits"])
            # `weight` is the relative per-variant weight (default 1.0 when the
            # tileset has no `weight` custom-data layer); the matcher normalizes
            # a signature's variant weights at pick time.
            by_sig.setdefault(key, []).append(
                {"source_id": t["source_id"], "coords": t["coords"], "weight": t.get("weight", _DEFAULT_WEIGHT)}
            )

        expected_keys = {_sig_key(list(sig)) for sig in expected}
        covered_keys = set(by_sig.keys())
        missing_keys = sorted(expected_keys - covered_keys)
        duplicated_keys = sorted(k for k, tiles in by_sig.items() if len(tiles) > 1)
        unexpected_keys = sorted(covered_keys - expected_keys)  # covered but not a valid class for this mode

        if unexpected_keys:
            warnings.append(
                f"terrain_set {tsi}: {len(unexpected_keys)} tile(s) carry a peering-bit signature that is not "
                f"a valid class for mode {mode} (engine allowed setting invalid bits; audit ignores them for "
                "coverage purposes): " + ", ".join(unexpected_keys[:10])
            )

        terrain_name = next(iter(terrain_names.values()), "")
        coverage[str(tsi)] = {
            "mode": mode,
            "terrain_name": terrain_name,
            "expected_count": len(expected_keys),
            "covered_count": len(covered_keys & expected_keys),
            "missing": missing_keys,
            "variants": {k: by_sig[k] for k in duplicated_keys},
            "signatures": by_sig,
        }

    # Unused tiles: no terrain (terrain == -1) AND no custom data, anywhere
    # in the dump (not scoped — an unused tile has no terrain_set to scope by).
    unused = [
        {"source_id": t["source_id"], "coords": t["coords"]}
        for t in all_tiles
        if t["terrain"] == -1 and t["terrain_set"] == -1 and not t.get("custom_data")
    ]

    return {
        "ok": True,
        "errors": errors,
        "warnings": warnings,
        "coverage": coverage,
        "unused_tiles": unused,
        "broken_ordering": broken_ordering,
        "tile_count": len(all_tiles),
        "terrain_set_count": len(all_terrain_sets),
    }


def _format_audit_report(report: dict, tileset_path: str) -> str:
    if not report.get("ok"):
        return f"ERROR — terrain_audit: {report.get('error', 'unknown audit error')}"

    lines = [f"Audit: {tileset_path}", f"  tiles: {report['tile_count']}  terrain sets: {report['terrain_set_count']}"]

    errors = report.get("errors") or []
    warnings = report.get("warnings") or []
    if not errors and not warnings:
        lines.append("  CLEAN — no errors or warnings.")
    if errors:
        lines.append(f"  ERRORS ({len(errors)}):")
        for e in errors:
            lines.append(f"    - {e}")
    if warnings:
        lines.append(f"  warnings ({len(warnings)}):")
        for w in warnings:
            lines.append(f"    - {w}")

    if report["coverage"]:
        lines.append("")
        lines.append("| terrain_set | terrain | mode | expected | covered | missing | variants |")
        lines.append("|---|---|---|---|---|---|---|")
        for tsi, cov in report["coverage"].items():
            lines.append(
                f"| {tsi} | {cov['terrain_name']} | {cov['mode']} | {cov['expected_count']} | "
                f"{cov['covered_count']} | {len(cov['missing'])} | {len(cov['variants'])} |"
            )
        for tsi, cov in report["coverage"].items():
            if cov["missing"]:
                shown = [m if m else "(isolated/no-neighbors)" for m in cov["missing"][:20]]
                lines.append(f"  terrain_set {tsi} missing signatures: " + "; ".join(shown))
            if cov["variants"]:
                vshown = list(cov["variants"].keys())[:10]
                lines.append(f"  terrain_set {tsi} variant signatures (allowed, seeded pick): " + "; ".join(vshown))

    unused = report.get("unused_tiles") or []
    if unused:
        lines.append(f"  unused tiles ({len(unused)}, no terrain + no custom data): " + ", ".join(f"src {u['source_id']} {tuple(u['coords'])}" for u in unused[:10]))

    if report["coverage"]:
        lines.append("")
        lines.append("Machine coverage payload (the in-house matcher parses this block; do not reformat by hand):")
        lines.append("```json")
        lines.append(json.dumps(report["coverage"], indent=2))
        lines.append("```")

    return "\n".join(lines)


def terrain_audit(tileset_path: str, terrain_set: int = -1, timeout: int = 60) -> str:
    """Audit a `.tres` TileSet's terrain-peering-bit coverage against the
    water-bottom law, headless.

    Loads the TileSet, dumps per-tile terrain_set/terrain/peering-bits/
    animation facts, and reports (per terrain set): the EXPECTED signature set
    for the set's mode, derived from the mode's valid-bit enumeration (reusing
    `blob47_table`/`blob16_sides_table`/`blob16_corners_table` — never a
    hardcoded count: 47 for MATCH_CORNERS_AND_SIDES, 16 for MATCH_SIDES/
    MATCH_CORNERS, but that number is `len()` of the reused table, not written
    down anywhere); which signatures are covered/missing/duplicated (a
    duplicate — two tiles sharing one signature — is ALLOWED and reported as a
    variant, not an error, since the in-house matcher's seeded pick consumes
    variants); tiles with terrain != -1 but terrain_set == -1 (broken
    ordering, reported as an error); terrain sets with more than one terrain
    (water-bottom law violation, error); unused tiles (no terrain, no custom
    data); and the animation sync lint (every animated terrain-bearing tile
    must share identical frames/duration and mode == DEFAULT — a desynced or
    random-start water tile is an ERROR, not a warning, because it breaks
    coastline phase-sync).

    terrain_set=-1 (default) audits every terrain set in the TileSet; passing
    a specific index scopes the coverage table to just that set (broken-
    ordering, unused-tile, and >1-terrain-per-set checks are NOT scope-limited
    since those are per-tile/per-set data-integrity checks independent of
    which set the caller asked to focus on).

    Returns a markdown report AND embeds a machine `coverage` dict the in-house
    matcher (game repo) consumes, as a fenced ```json code block appended
    after the markdown (present whenever any terrain sets were audited;
    absent only on a load/scope error, whose result is a plain "ERROR —"
    string). `coverage` shape (STABLE — do not rename keys without updating
    the game-repo matcher spec):

        coverage: dict[str, dict]   # key = str(terrain_set index)
          mode: str                 # "MATCH_CORNERS_AND_SIDES" | "MATCH_SIDES" | "MATCH_CORNERS"
          terrain_name: str         # the set's one terrain's name (water-bottom law: exactly one)
          expected_count: int       # size of the mode's canonical signature-class set
          covered_count: int        # how many of those classes have >=1 tile
          missing: list[str]        # signature keys with NO tile (see key format below)
          variants: dict[str, list[dict]]   # signature keys with >1 tile (allowed)
          signatures: dict[str, list[dict]] # EVERY covered signature -> its tile(s)
            each tile dict: {"source_id": int, "coords": [x, y], "weight": float}

        Signature key format: comma-joined, alphabetically-sorted CellNeighbor
        bit names present in that signature (e.g. "BOTTOM_SIDE,RIGHT_SIDE"),
        or "" for the isolated/no-neighbors signature. The matcher computes
        its own 8-neighbor occupancy signature the same way (sorted, comma-
        joined bit names) and looks it up directly in `signatures`.

        The `weight` per tile dict is the RELATIVE per-variant weight, read off
        the tile's `weight` custom-data layer (default 1.0 when the tileset has
        no such layer, i.e. an unweighted build). The matcher normalizes a
        signature's variant weights at pick time, so a variant's probability is
        proportional to its weight; equal weights reduce to the uniform pick.

    Never raises — load/scope errors come back as a structured "ERROR —" string.
    """
    try:
        ts_res = config.resolve_project_path(tileset_path)
    except config.PathEscapeError:
        return f"Refused: {tileset_path} resolves outside the project root."
    if tileset_path.startswith("res://"):
        ts_path_res = tileset_path
    else:
        root = config.PROJECT_ROOT.resolve()
        ts_path_res = "res://" + ts_res.resolve().relative_to(root).as_posix()

    nonce, _, _ = make_sentinels()
    source = compose_audit_script(ts_path_res, nonce)

    parse_err = _parse_check(source)
    if parse_err:
        return f"ERROR — composed audit script did not parse:\n{parse_err}"

    r = runner.run_temp_probe(source, timeout=timeout)
    if r.get("timeout"):
        return f"UNAVAILABLE — terrain_audit timed out after {timeout}s (Godot may be unavailable)."
    if r.get("rc") is None:
        return f"UNAVAILABLE — {r.get('err') or 'terrain_audit could not launch Godot.'}"

    out = r.get("out") or ""
    payload, reason = parse_sentinel_json(out, nonce)
    if payload is None:
        tail = (r.get("err") or out).strip()
        return f"UNAVAILABLE — terrain_audit produced no parseable report ({reason}).\n{tail[-800:]}"

    report = _audit_report(payload, terrain_set)
    return _format_audit_report(report, ts_path_res)
