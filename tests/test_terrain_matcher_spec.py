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


# --- WEIGHTED seeded variant pick (the second half of the port) --------------
# When a signature has >1 variant tile (the audit `coverage[set]["signatures"]`
# list), the matcher picks ONE per cell, DETERMINISTICALLY (same seed+cell ->
# same tile) but with a variant's probability PROPORTIONAL to its `weight`. This
# is what lets a biome interior be mostly one tile (plain grass 0.9) with rare
# variants (tufts 0.05 each). Equal weights reduce EXACTLY to the prior uniform
# pick (back-compat). The game ports both functions into terrain_matcher.gd.

_U32 = 0xFFFFFFFF


def _cell_hash01(seed, x, y):
    """Deterministic, position-stable pseudo-random value in [0, 1) for a cell.

    A small FNV-1a-style 32-bit mix over (seed, x, y). Pure integer ops so a
    GDScript port produces bit-identical values (Godot ints are 64-bit; the
    `& _U32` masks keep every step inside 32 bits). NOT for cryptography — only
    for a stable per-cell roll.
    """
    h = 2166136261
    for v in (seed, x & _U32, y & _U32):
        h ^= v & _U32
        h = (h * 16777619) & _U32
        # extra avalanche so adjacent cells don't correlate
        h ^= (h >> 15)
        h = (h * 2246822519) & _U32
    h ^= (h >> 13)
    h &= _U32
    return h / 4294967296.0  # [0, 1)


def pick_variant(variants, x, y, seed):
    """Pick one variant tile for cell (x, y) by a deterministic WEIGHTED roll.

    `variants` is the audit's `signatures[key]` list — each a dict with at least
    `source_id`, `coords` [ax, ay], and `weight` (relative, positive; default
    1.0 for unweighted builds). Steps:
      1. sort variants position-stably by (source_id, atlas_x, atlas_y) so the
         cumulative distribution is order-independent of the audit's dict order;
      2. normalize the weights into a cumulative distribution over [0, total);
      3. roll u in [0, 1) from _cell_hash01(seed, x, y) and return the variant
         whose cumulative interval contains u * total.
    Determinism: same (variants, x, y, seed) -> same tile. Weighting: a
    variant's chance is weight_i / sum(weight). Back-compat: when all weights are
    equal the interval boundaries fall at i/n * total, so this reduces to
    int(u * n) over the sorted variants — the prior uniform pick, exactly.
    """
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
    return ordered[-1]  # float-rounding guard: u->1.0 boundary lands on the last


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


def _variant(source_id, ax, ay, weight):
    """A variant tile in the audit `signatures[key]` shape."""
    return {"source_id": source_id, "coords": [ax, ay], "weight": weight}


class TestWeightedVariantPick:
    """Locks the WEIGHTED seeded pick: deterministic per cell, probability
    proportional to weight, and (back-compat) equal weights reproduce the prior
    uniform pick exactly. The game ports `pick_variant` verbatim."""

    # A 90/5/5 interior: plain grass heavy, two tuft variants rare.
    _PLAIN = _variant(source_id=0, ax=3, ay=0, weight=0.9)
    _TUFT_A = _variant(source_id=0, ax=4, ay=0, weight=0.05)
    _TUFT_B = _variant(source_id=0, ax=5, ay=0, weight=0.05)

    def test_pick_is_deterministic_per_cell(self):
        """Same (variants, cell, seed) -> same tile, every time."""
        variants = [self._PLAIN, self._TUFT_A, self._TUFT_B]
        for (x, y) in [(0, 0), (7, 3), (40, 91), (-5, 12)]:
            first = pick_variant(variants, x, y, seed=1234)
            for _ in range(5):
                assert pick_variant(variants, x, y, seed=1234) == first

    def test_pick_is_independent_of_input_order(self):
        """Sorting by (source_id, atlas_x, atlas_y) makes the pick independent
        of the order the audit happened to list the variants in."""
        a = [self._PLAIN, self._TUFT_A, self._TUFT_B]
        b = [self._TUFT_B, self._PLAIN, self._TUFT_A]
        for (x, y) in [(0, 0), (11, 4), (33, 33)]:
            assert pick_variant(a, x, y, seed=99) == pick_variant(b, x, y, seed=99)

    def test_relative_weights_scale_invariant(self):
        """RELATIVE weights: [0.9, 0.05, 0.05] and [18, 1, 1] must pick the same
        tile for every cell (only the ratio matters, not the magnitude)."""
        frac = [self._PLAIN, self._TUFT_A, self._TUFT_B]
        integ = [_variant(0, 3, 0, 18), _variant(0, 4, 0, 1), _variant(0, 5, 0, 1)]
        for (x, y) in [(x, y) for x in range(10) for y in range(10)]:
            fp = pick_variant(frac, x, y, seed=7)
            ip = pick_variant(integ, x, y, seed=7)
            assert fp["coords"] == ip["coords"]

    def test_distribution_approximates_the_weights(self):
        """Over a fixed-seed grid, a 90/5/5 split must land ~90% on the heavy
        tile and ~5% on each tuft, within tolerance — the whole point of the
        feature (mostly plain grass, sparse tufts)."""
        variants = [self._PLAIN, self._TUFT_A, self._TUFT_B]
        counts = {(3, 0): 0, (4, 0): 0, (5, 0): 0}
        n = 0
        for x in range(120):
            for y in range(120):
                pick = pick_variant(variants, x, y, seed=2024)
                counts[tuple(pick["coords"])] += 1
                n += 1
        assert n == 14400
        plain = counts[(3, 0)] / n
        tuft_a = counts[(4, 0)] / n
        tuft_b = counts[(5, 0)] / n
        assert 0.86 <= plain <= 0.94, f"plain share {plain:.3f} off the 0.90 target"
        assert 0.02 <= tuft_a <= 0.08, f"tuft_a share {tuft_a:.3f} off the 0.05 target"
        assert 0.02 <= tuft_b <= 0.08, f"tuft_b share {tuft_b:.3f} off the 0.05 target"

    def test_equal_weights_reduce_to_uniform_pick_exactly(self):
        """Back-compat: with equal weights the weighted pick must return the
        SAME tile as int(u * n) over the sorted variants — the prior uniform
        behavior, bit-for-bit — for every cell in a grid."""
        equal = [_variant(0, 3, 0, 1.0), _variant(0, 4, 0, 1.0), _variant(0, 5, 0, 1.0)]
        ordered = sorted(equal, key=lambda t: (t["source_id"], t["coords"][0], t["coords"][1]))
        n = len(ordered)
        for x in range(60):
            for y in range(60):
                u = _cell_hash01(2024, x, y)
                uniform = ordered[min(int(u * n), n - 1)]
                assert pick_variant(equal, x, y, seed=2024) == uniform

    def test_default_weight_when_absent_is_uniform(self):
        """A variant list from an UNWEIGHTED build omits `weight`; the pick must
        treat missing weight as 1.0, i.e. behave uniformly (no crash, no bias)."""
        bare = [
            {"source_id": 0, "coords": [3, 0]},
            {"source_id": 0, "coords": [4, 0]},
        ]
        counts = {(3, 0): 0, (4, 0): 0}
        for x in range(80):
            for y in range(80):
                counts[tuple(pick_variant(bare, x, y, seed=5)["coords"])] += 1
        share = counts[(3, 0)] / (counts[(3, 0)] + counts[(4, 0)])
        assert 0.44 <= share <= 0.56, f"unweighted share {share:.3f} not ~uniform"

    def test_single_variant_always_picked(self):
        one = [self._PLAIN]
        for (x, y) in [(0, 0), (5, 9), (100, 3)]:
            assert pick_variant(one, x, y, seed=1) == self._PLAIN
