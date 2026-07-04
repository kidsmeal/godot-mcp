"""Offline spec-lock for the in-house terrain matcher (S1 verdict, 2026-07-04).

The matcher itself SHIPS in the game repo (systems/worldgen/terrain_matcher.gd);
it is deliberately NOT an mcp tool. This file locks the load-bearing part — the
MATCH_CORNERS signature computation the game ports verbatim — as a pure-Python
reference with a committed unit test, so the port is a copy, not a redesign, and
so the spec cannot silently drift. No Godot binary required.

Grounding this test encodes (surfaced live by the S1 spike against Godot 4.6.2):
square-grid MATCH_CORNERS uses the FOUR DIAGONAL corner peering bits
(TOP_RIGHT/BOTTOM_RIGHT/BOTTOM_LEFT/TOP_LEFT_CORNER), NOT the axis-aligned
CORNER bits that procgen.blob16_corners_table currently emits — those are
hex/iso grid bits that `TileData.is_valid_terrain_peering_bit` rejects on a
square grid. The matcher derives each diagonal corner via the Wang-corner rule
(the diagonal neighbor AND its two flanking cardinals must all be ground). The
signature-key format matches what procgen.terrain_audit emits: set corner-bit
names, sorted, comma-joined ("" = isolated).
"""
from __future__ import annotations

# --- PORT-READY reference (mirrors terrain_matcher.gd's core; the game copies
# this derivation into GDScript) --------------------------------------------

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
_DIAG_BITS = ("TOP_RIGHT_CORNER", "BOTTOM_RIGHT_CORNER", "BOTTOM_LEFT_CORNER", "TOP_LEFT_CORNER")


def corner_signature_key(mask, x, y):
    """MATCH_CORNERS diagonal-corner signature key for the ground cell (x, y).

    `mask(x, y) -> bool` is True iff that cell is ground on the same layer;
    off-mask cells are water (the water-bottom law's centered eroded rect means
    land never reaches a border). A diagonal corner is set iff the diagonal
    neighbor and BOTH flanking cardinals are ground. Returns the canonical key
    terrain_audit emits (sorted, comma-joined bit names; "" = isolated).
    """
    bits = []
    for bit_name, (a, d, b) in _CORNER_RULE.items():
        ax, ay = _NEIGHBOR_OFFSETS[a]
        dx, dy = _NEIGHBOR_OFFSETS[d]
        bx, by = _NEIGHBOR_OFFSETS[b]
        if mask(x + ax, y + ay) and mask(x + dx, y + dy) and mask(x + bx, y + by):
            bits.append(bit_name)
    return ",".join(sorted(bits))


def _toy_mask(size=20):
    """The S1 toy landmass: centered eroded rect, an L-notch bay on the right,
    and an interior pond — the exact fixture the S1 verdict's asserts use."""
    ground = set()
    lo, hi = 2, size - 3
    for y in range(lo, hi + 1):
        for x in range(lo, hi + 1):
            ground.add((x, y))
    for y in range(9, 12):
        for x in range(13, 18):
            ground.discard((x, y))
    ground -= {(5, 5), (6, 5), (5, 6), (6, 6)}
    return lambda x, y: (x, y) in ground


class TestCornerSignatureSpec:
    def test_interior_cell_sets_all_four_diagonal_corners(self):
        mask = _toy_mask()
        assert corner_signature_key(mask, 3, 16) == (
            "BOTTOM_LEFT_CORNER,BOTTOM_RIGHT_CORNER,TOP_LEFT_CORNER,TOP_RIGHT_CORNER"
        )

    def test_straight_top_edge_sets_only_the_two_bottom_corners(self):
        mask = _toy_mask()
        assert corner_signature_key(mask, 8, 2) == "BOTTOM_LEFT_CORNER,BOTTOM_RIGHT_CORNER"

    def test_straight_left_edge_sets_only_the_two_right_corners(self):
        mask = _toy_mask()
        assert corner_signature_key(mask, 2, 10) == "BOTTOM_RIGHT_CORNER,TOP_RIGHT_CORNER"

    def test_convex_outer_corner_sets_one_diagonal_only(self):
        """Island top-left tip: N and W are water, so only the BOTTOM_RIGHT
        corner (S+SE+E all ground) is set."""
        mask = _toy_mask()
        assert corner_signature_key(mask, 2, 2) == "BOTTOM_RIGHT_CORNER"

    def test_concave_inner_corner_sets_three_diagonals(self):
        """Land cell SE of the interior pond: the NW diagonal fails (pond cell
        (6,6) is water), the other three diagonals are ground — an inner corner
        distinct from both interior and the convex outer corner."""
        mask = _toy_mask()
        assert corner_signature_key(mask, 7, 7) == (
            "BOTTOM_LEFT_CORNER,BOTTOM_RIGHT_CORNER,TOP_RIGHT_CORNER"
        )

    def test_out_of_bounds_is_water(self):
        """A lone ground cell surrounded by out-of-bounds resolves to the
        isolated signature — off-mask is water (land never reaches a border)."""
        def mask(x, y):
            return (x, y) == (0, 0)
        assert corner_signature_key(mask, 0, 0) == ""

    def test_the_sixteen_reachable_classes_are_subsets_of_the_diagonal_bits(self):
        """Every signature the matcher can emit is a subset of the 4 diagonal
        corner bits — 16 classes, the correct square-grid MATCH_CORNERS set.
        Sweeping every 3x3 same-layer occupancy pattern must never yield a
        signature outside that set (guards the port against emitting the wrong
        axis-aligned bits)."""
        seen = set()
        for pattern in range(1 << 8):
            present = set()
            i = 0
            for d in ("N", "E", "S", "W", "NE", "SE", "SW", "NW"):
                if pattern & (1 << i):
                    present.add(_NEIGHBOR_OFFSETS[d])
                i += 1

            def mask(x, y, present=present):
                if (x, y) == (0, 0):
                    return True
                return (x, y) in present

            key = corner_signature_key(mask, 0, 0)
            seen.add(key)
            for bit in (key.split(",") if key else []):
                assert bit in _DIAG_BITS, f"emitted non-diagonal bit {bit!r}"
        # all 16 subsets of the 4 diagonal corners are reachable
        assert len(seen) == 16
