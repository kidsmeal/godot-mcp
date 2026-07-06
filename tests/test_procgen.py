"""Offline tests for the procgen module (Phase 1: tileset_build).

No real Godot binary required — these exercise the pure-Python surface: the
hardened nonce sentinel, the blob autotile tables, config validation, and the
GDScript composition. The live headless build is covered by
test_procgen_build.py (skipped when Godot is unavailable).
"""
from __future__ import annotations

import pytest

from godot_mcp import procgen

# --- Hardened sentinel ------------------------------------------------------


class TestSentinelHardening:
    def test_make_sentinels_are_nonce_framed_and_unique(self):
        nonce_a, begin_a, end_a = procgen.make_sentinels()
        nonce_b, begin_b, end_b = procgen.make_sentinels()
        assert begin_a.startswith("PROCGEN_JSON_BEGIN:")
        assert end_a.startswith("PROCGEN_JSON_END:")
        assert nonce_a in begin_a and nonce_a in end_a
        assert nonce_a != nonce_b  # fresh per run

    def test_parse_roundtrips_json(self):
        nonce, begin, end = procgen.make_sentinels()
        out = f"boot noise\n{begin}\n{{\"ok\": true, \"n\": 3}}\n{end}\n"
        payload, reason = procgen.parse_sentinel_json(out, nonce)
        assert reason == ""
        assert payload == {"ok": True, "n": 3}

    def test_payload_containing_bare_end_marker_does_not_truncate(self):
        """The core P0 hardening: a payload whose data contains the literal
        'PROCGEN_JSON_END' string must NOT truncate parsing. The nonce'd end
        marker is what closes the block, and the payload cannot contain it."""
        nonce, begin, end = procgen.make_sentinels()
        # atlas name literally contains the bare end marker
        body = '{"atlas": "sheet PROCGEN_JSON_END weird", "ok": true}'
        out = f"{begin}\n{body}\n{end}\n"
        payload, reason = procgen.parse_sentinel_json(out, nonce)
        assert reason == ""
        assert payload["atlas"] == "sheet PROCGEN_JSON_END weird"
        assert payload["ok"] is True

    def test_missing_end_sentinel_reports_reason(self):
        nonce, begin, _end = procgen.make_sentinels()
        out = f"{begin}\n{{\"ok\": true}}\n"
        payload, reason = procgen.parse_sentinel_json(out, nonce)
        assert payload is None
        assert "end sentinel" in reason

    def test_wrong_nonce_does_not_match_another_runs_block(self):
        nonce_a, begin_a, end_a = procgen.make_sentinels()
        nonce_b, _b, _e = procgen.make_sentinels()
        out = f"{begin_a}\n{{\"ok\": true}}\n{end_a}\n"
        payload, reason = procgen.parse_sentinel_json(out, nonce_b)
        assert payload is None
        assert "begin sentinel" in reason


# --- blob autotile tables ---------------------------------------------------


class TestBlob47Table:
    def test_has_exactly_47_entries(self):
        table = procgen.blob47_table()
        assert len(table) == 47

    def test_isolated_tile_has_no_bits(self):
        """Config 0 (grid origin) is the isolated tile — no neighbors filled,
        so no peering bits at all."""
        table = procgen.blob47_table(width=8)
        assert table[(0, 0)] == []

    def test_full_interior_tile_has_all_eight_bits(self):
        """The last config is the full-interior tile: all 4 sides + all 4
        diagonal corners."""
        table = procgen.blob47_table(width=8)
        # config 46 -> (col, row) = (46 % 8, 46 // 8) = (6, 5)
        bits = set(table[(6, 5)])
        assert bits == {
            "TOP_SIDE", "RIGHT_SIDE", "BOTTOM_SIDE", "LEFT_SIDE",
            "TOP_RIGHT_CORNER", "BOTTOM_RIGHT_CORNER", "BOTTOM_LEFT_CORNER", "TOP_LEFT_CORNER",
        }

    def test_single_side_configs_carry_exactly_that_side(self):
        """Configs 1-4 are the single-side cases in side-index order N,E,S,W."""
        table = procgen.blob47_table(width=8)
        assert table[(1, 0)] == ["TOP_SIDE"]      # config 1: N
        assert table[(2, 0)] == ["RIGHT_SIDE"]    # config 2: E
        assert table[(3, 0)] == ["BOTTOM_SIDE"]   # config 3: S
        assert table[(4, 0)] == ["LEFT_SIDE"]     # config 4: W

    def test_no_config_has_a_corner_without_both_adjacent_sides(self):
        """The corner-validity rule: every corner bit present implies both its
        adjacent side bits are present. This is what makes the count 47."""
        adj = {
            "TOP_RIGHT_CORNER": ("TOP_SIDE", "RIGHT_SIDE"),
            "BOTTOM_RIGHT_CORNER": ("BOTTOM_SIDE", "RIGHT_SIDE"),
            "BOTTOM_LEFT_CORNER": ("BOTTOM_SIDE", "LEFT_SIDE"),
            "TOP_LEFT_CORNER": ("TOP_SIDE", "LEFT_SIDE"),
        }
        for bits in procgen.blob47_table().values():
            bitset = set(bits)
            for corner, (s1, s2) in adj.items():
                if corner in bitset:
                    assert s1 in bitset and s2 in bitset, f"{corner} present without {s1}/{s2}"

    def test_width_changes_layout_not_content(self):
        wide = procgen.blob47_table(width=8)
        narrow = procgen.blob47_table(width=4)
        # same set of bit-sets, just reflowed
        assert sorted(sorted(v) for v in wide.values()) == sorted(sorted(v) for v in narrow.values())


class TestBlob16Tables:
    def test_sides_table_has_16_entries_side_bits_only(self):
        table = procgen.blob16_sides_table()
        assert len(table) == 16
        allowed = {"TOP_SIDE", "RIGHT_SIDE", "BOTTOM_SIDE", "LEFT_SIDE"}
        for bits in table.values():
            assert set(bits) <= allowed

    def test_corners_table_has_16_entries_diagonal_corner_bits_only(self):
        """MATCH_CORNERS on a square grid uses the DIAGONAL corner bits (the
        same ones blob47 uses), NOT the axis-aligned TOP_CORNER/RIGHT_CORNER/
        BOTTOM_CORNER/LEFT_CORNER bits — those are hex/isometric-only and
        `is_valid_terrain_peering_bit` rejects them on a square grid."""
        table = procgen.blob16_corners_table()
        assert len(table) == 16
        allowed = {"TOP_RIGHT_CORNER", "BOTTOM_RIGHT_CORNER", "BOTTOM_LEFT_CORNER", "TOP_LEFT_CORNER"}
        for bits in table.values():
            assert set(bits) <= allowed

    def test_corners_table_yields_16_distinct_signatures(self):
        table = procgen.blob16_corners_table()
        signatures = {frozenset(bits) for bits in table.values()}
        assert len(signatures) == 16

    def test_corners_empty_and_full(self):
        table = procgen.blob16_corners_table(width=4)
        assert table[(0, 0)] == []  # mask 0
        assert set(table[(3, 3)]) == {
            "TOP_RIGHT_CORNER", "BOTTOM_RIGHT_CORNER", "BOTTOM_LEFT_CORNER", "TOP_LEFT_CORNER",
        }  # mask 15

    def test_sides_empty_and_full(self):
        table = procgen.blob16_sides_table(width=4)
        assert table[(0, 0)] == []  # mask 0
        assert set(table[(3, 3)]) == {"TOP_SIDE", "RIGHT_SIDE", "BOTTOM_SIDE", "LEFT_SIDE"}  # mask 15


class TestMinifantasyEdgesTable:
    """The 3x5 Minifantasy biome edge block. The cell->LAND-corner arrangement
    was read empirically off the real ForgottenPlains grass-water block (cols
    25-27, rows 3-7) and confirmed identical on the DesolateDesert block (cols
    20-22, rows 5-9) — see `_MINIFANTASY_EDGES_LAND_CORNERS`. These lock that
    reading so a permutation error (which would scramble coastlines even with a
    clean audit) can never slip in unnoticed."""

    # The empirically-read table (block-relative col,row -> the DIAGONAL corner
    # bits that are LAND). Duplicated here from the module ON PURPOSE: this is
    # the spec the visual read produced, so the test must fail if the module's
    # table is edited to disagree with the eyeball, not silently track it.
    _EXPECTED = {
        (0, 0): {"TOP_LEFT_CORNER", "TOP_RIGHT_CORNER", "BOTTOM_LEFT_CORNER"},
        (1, 0): {"TOP_LEFT_CORNER", "TOP_RIGHT_CORNER"},
        (2, 0): {"TOP_LEFT_CORNER", "TOP_RIGHT_CORNER", "BOTTOM_RIGHT_CORNER"},
        (0, 1): {"TOP_LEFT_CORNER", "BOTTOM_LEFT_CORNER"},
        (1, 1): set(),
        (2, 1): {"TOP_RIGHT_CORNER", "BOTTOM_RIGHT_CORNER"},
        (0, 2): {"TOP_LEFT_CORNER", "BOTTOM_LEFT_CORNER", "BOTTOM_RIGHT_CORNER"},
        (1, 2): {"BOTTOM_LEFT_CORNER", "BOTTOM_RIGHT_CORNER"},
        (2, 2): {"TOP_RIGHT_CORNER", "BOTTOM_LEFT_CORNER", "BOTTOM_RIGHT_CORNER"},
        (0, 3): {"TOP_LEFT_CORNER"},
        (1, 3): {"TOP_RIGHT_CORNER"},
        (2, 3): {"TOP_LEFT_CORNER", "BOTTOM_RIGHT_CORNER"},
        (0, 4): {"BOTTOM_LEFT_CORNER"},
        (1, 4): {"BOTTOM_RIGHT_CORNER"},
        (2, 4): {"TOP_RIGHT_CORNER", "BOTTOM_LEFT_CORNER"},
    }
    _DIAG = {"TOP_LEFT_CORNER", "TOP_RIGHT_CORNER", "BOTTOM_LEFT_CORNER", "BOTTOM_RIGHT_CORNER"}

    def test_has_exactly_15_cells_in_a_3x5_block(self):
        table = procgen.minifantasy_edges_table()
        assert len(table) == 15
        assert {c for (c, _r) in table} == {0, 1, 2}
        assert {r for (_c, r) in table} == {0, 1, 2, 3, 4}

    def test_every_cell_carries_the_empirically_read_signature(self):
        """Each of the 15 cells must emit exactly the LAND diagonal corners
        read off the real sheet — this is the load-bearing cell->signature order
        that a wrong permutation would scramble."""
        table = procgen.minifantasy_edges_table()
        for cell, expected_bits in self._EXPECTED.items():
            assert set(table[cell]) == expected_bits, f"cell {cell} signature drifted"

    def test_only_diagonal_corner_bits_are_emitted(self):
        """Square-grid MATCH_CORNERS: only the 4 diagonal corner bits are valid;
        the axis-aligned TOP_CORNER/... bits must never appear."""
        for bits in procgen.minifantasy_edges_table().values():
            assert set(bits) <= self._DIAG

    def test_covers_15_of_16_match_corners_classes_no_duplicates(self):
        """The pond-ring block hits 15 distinct MATCH_CORNERS classes with no
        duplicates; the single absent class is the full-interior (all 4 corners
        land) tile — the exact expectation `procgen_terrain_audit` reports as
        15 covered / 1 missing for a sheet built with this strategy."""
        table = procgen.minifantasy_edges_table()
        sigs = [frozenset(bits) for bits in table.values()]
        assert len(sigs) == len(set(sigs)) == 15  # no duplicates
        expected = procgen.expected_signature_set("MATCH_CORNERS")  # all 16 classes
        covered = set(sigs)
        missing = expected - covered
        assert covered <= expected
        assert missing == {frozenset(self._DIAG)}  # only the all-corners interior is absent

    def test_translated_by_origin_like_the_other_blob_strategies(self):
        """`_resolve_assign_bits` must translate the block-relative offsets by
        the terrain_assign's origin, so one table serves every biome sheet at
        its own atlas position (plains at (25,3), desert at (20,5), ...)."""
        asn = {"strategy": "minifantasy_edges", "terrain": "grass", "origin": [25, 3]}
        resolved = procgen._resolve_assign_bits(asn, (25, 3))
        # 15 tiles, all inside the 3x5 block anchored at (25,3)
        assert len(resolved) == 15
        assert set(resolved) == {(25 + c, 3 + r) for c in range(3) for r in range(5)}
        # block cell (2,3) (TL,BR diagonal) lands at atlas (27, 6)
        assert set(resolved[(27, 6)]) == {"TOP_LEFT_CORNER", "BOTTOM_RIGHT_CORNER"}
        # the water-center cell (1,1) at atlas (26,4) carries no bits
        assert resolved[(26, 4)] == []

    def test_interior_cells_get_exactly_the_four_diagonal_corner_bits(self):
        """The `interior` param supplies the full-interior all-4-corners class the
        15-cell pond block omits. Each listed ABSOLUTE atlas cell must resolve to
        exactly the 4 diagonal corner bits (TL,TR,BL,BR) — no more, no less, and
        never an axis-aligned CORNER bit."""
        asn = {
            "strategy": "minifantasy_edges",
            "terrain": "grass",
            "origin": [25, 3],
            "interior": [[2, 3], [3, 3], [4, 3]],
        }
        resolved = procgen._resolve_assign_bits(asn, (25, 3))
        # 15 block cells + 3 interior fill cells, all distinct coords
        assert len(resolved) == 18
        all_corners = {
            "TOP_LEFT_CORNER", "TOP_RIGHT_CORNER", "BOTTOM_LEFT_CORNER", "BOTTOM_RIGHT_CORNER",
        }
        for cell in [(2, 3), (3, 3), (4, 3)]:
            assert set(resolved[cell]) == all_corners, f"interior {cell} not all-4-corners"
            assert len(resolved[cell]) == 4, f"interior {cell} has duplicate/extra bits"

    def test_interior_cells_are_absolute_not_origin_translated(self):
        """Interior coords are ABSOLUTE atlas cells (the biome's solid-ground fill
        area), NOT block-relative — they must NOT be shifted by `origin`."""
        asn = {
            "strategy": "minifantasy_edges",
            "terrain": "grass",
            "origin": [25, 3],
            "interior": [[2, 3]],
        }
        resolved = procgen._resolve_assign_bits(asn, (25, 3))
        assert (2, 3) in resolved  # exactly where the config named it
        assert (27, 6) in resolved  # the edge block is still origin-translated

    def test_interior_omitted_leaves_the_bare_15_cell_block(self):
        """No `interior` key -> unchanged 15-cell behavior (the all-corners class
        stays missing), so the param is a pure, opt-in extension."""
        asn = {"strategy": "minifantasy_edges", "terrain": "grass", "origin": [0, 0]}
        resolved = procgen._resolve_assign_bits(asn, (0, 0))
        assert len(resolved) == 15
        all_corners = {
            "TOP_LEFT_CORNER", "TOP_RIGHT_CORNER", "BOTTOM_LEFT_CORNER", "BOTTOM_RIGHT_CORNER",
        }
        assert all(set(b) != all_corners for b in resolved.values())


# --- per-variant weighting: config parse + resolution -----------------------


class TestWeightedInteriorResolution:
    """Weights ride the SAME `interior` rail variants already use: a bare
    [col,row] is the unweighted default (1.0), a [col,row,weight] carries an
    explicit RELATIVE weight. `_resolve_assign_bits` still maps coords->bits
    (weighted or not); `_resolve_assign_weights` is the parallel coords->weight
    rail (explicit weights only; default cells are filled at bake time)."""

    def test_parse_weighted_cell_accepts_both_shapes(self):
        assert procgen._parse_weighted_cell([3, 0]) == ((3, 0), 1.0)
        assert procgen._parse_weighted_cell([3, 0, 0.9]) == ((3, 0), 0.9)
        # ints are fine as a relative weight (18,1,1 behaves like 0.9,0.05,0.05)
        assert procgen._parse_weighted_cell([4, 0, 18]) == ((4, 0), 18.0)

    def test_parse_weighted_cell_rejects_malformed(self):
        assert procgen._parse_weighted_cell([3]) is None            # too short
        assert procgen._parse_weighted_cell([3, 0, 0.5, 1]) is None  # too long
        assert procgen._parse_weighted_cell([3, 0, 0]) is None       # zero weight
        assert procgen._parse_weighted_cell([3, 0, -1.0]) is None    # negative weight
        assert procgen._parse_weighted_cell([3, 0, "x"]) is None     # non-numeric weight
        assert procgen._parse_weighted_cell([3, 0, True]) is None    # bool is not a weight
        assert procgen._parse_weighted_cell(["a", 0]) is None        # non-int coord
        assert procgen._parse_weighted_cell({"cell": [3, 0]}) is None  # dict shape not accepted

    def test_bits_resolve_identically_for_weighted_and_bare_interior(self):
        """A [col,row,weight] interior entry assigns the SAME all-4-corners bits
        as a bare [col,row] — the weight is orthogonal to the peering bits."""
        all_corners = {
            "TOP_LEFT_CORNER", "TOP_RIGHT_CORNER", "BOTTOM_LEFT_CORNER", "BOTTOM_RIGHT_CORNER",
        }
        bare = procgen._resolve_assign_bits(
            {"strategy": "minifantasy_edges", "terrain": "grass", "origin": [0, 0], "interior": [[3, 0]]}, (0, 0)
        )
        weighted = procgen._resolve_assign_bits(
            {"strategy": "minifantasy_edges", "terrain": "grass", "origin": [0, 0], "interior": [[3, 0, 0.9]]}, (0, 0)
        )
        assert set(bare[(3, 0)]) == all_corners
        assert set(weighted[(3, 0)]) == all_corners

    def test_resolve_weights_returns_only_explicit_weights(self):
        """Only cells with an EXPLICIT weight appear; a bare (default 1.0) cell
        is absent — the build fills those with _DEFAULT_WEIGHT at bake time."""
        asn = {
            "strategy": "minifantasy_edges",
            "terrain": "grass",
            "origin": [0, 0],
            "interior": [[3, 0, 0.9], [4, 0, 0.05], [5, 0]],  # last is bare/default
        }
        weights = procgen._resolve_assign_weights(asn, (0, 0))
        assert weights == {(3, 0): 0.9, (4, 0): 0.05}
        assert (5, 0) not in weights  # default cell not listed

    def test_resolve_weights_absolute_not_origin_translated(self):
        """Weighted interior coords are ABSOLUTE (like the bits), not shifted by
        origin — the weight lands on exactly the cell the config named."""
        asn = {
            "strategy": "minifantasy_edges",
            "terrain": "grass",
            "origin": [25, 3],
            "interior": [[2, 3, 0.9]],
        }
        assert procgen._resolve_assign_weights(asn, (25, 3)) == {(2, 3): 0.9}

    def test_no_interior_weights_is_empty(self):
        asn = {"strategy": "minifantasy_edges", "terrain": "grass", "origin": [0, 0]}
        assert procgen._resolve_assign_weights(asn, (0, 0)) == {}


# --- config validation ------------------------------------------------------


def _min_cfg() -> dict:
    return {
        "tileset": {"tile_size": [8, 8]},
        "atlas": [{"id": "ground", "texture": "res://art/ground.png", "scan": "non_transparent"}],
    }


class TestLoadConfigFormatDispatch:
    """P1-hardening finding #1: config is a 'TOML/JSON file' per the plan, but
    load_config previously only ever called tomllib. Dispatch on extension and
    prove a .json config produces the SAME validated dict shape as the
    equivalent .toml config."""

    _TOML = """
[tileset]
tile_size = [8, 8]

[[atlas]]
id = "ground"
texture = "res://art/ground.png"
scan = "non_transparent"

[[terrain_set]]
mode = "match_corners_and_sides"
terrains = [ { name = "grass", color = "#4c8f3c" } ]

[[terrain_assign]]
atlas = "ground"
strategy = "blob47"
terrain = "grass"

[[animation]]
atlas = "ground"
base_region = [[0, 4], [0, 4]]
frames = 2
frame_offset = [1, 0]
duration = 0.6
mode = "default"

[physics]
default_full_square = ["grass"]

[custom_data]
layers = [ { name = "biome_id", type = "string" } ]
"""

    def _equivalent_json(self) -> dict:
        return {
            "tileset": {"tile_size": [8, 8]},
            "atlas": [{"id": "ground", "texture": "res://art/ground.png", "scan": "non_transparent"}],
            "terrain_set": [{"mode": "match_corners_and_sides", "terrains": [{"name": "grass", "color": "#4c8f3c"}]}],
            "terrain_assign": [{"atlas": "ground", "strategy": "blob47", "terrain": "grass"}],
            "animation": [
                {
                    "atlas": "ground",
                    "base_region": [[0, 4], [0, 4]],
                    "frames": 2,
                    "frame_offset": [1, 0],
                    "duration": 0.6,
                    "mode": "default",
                }
            ],
            "physics": {"default_full_square": ["grass"]},
            "custom_data": {"layers": [{"name": "biome_id", "type": "string"}]},
        }

    def test_json_and_toml_configs_parse_and_validate_identically(self, tmp_path):
        import json

        toml_path = tmp_path / "plains.toml"
        toml_path.write_text(self._TOML, encoding="utf-8")
        json_path = tmp_path / "plains.json"
        json_path.write_text(json.dumps(self._equivalent_json()), encoding="utf-8")

        toml_cfg = procgen.load_config(str(toml_path))
        json_cfg = procgen.load_config(str(json_path))
        assert toml_cfg == json_cfg

    def test_json_config_composes_the_same_build_script_as_toml(self, tmp_path):
        """Beyond dict equality: the .json-loaded config must drive
        compose_build_script identically to the .toml-loaded one (an
        equivalent tileset), not just parse to the same shape."""
        import json

        toml_path = tmp_path / "plains.toml"
        toml_path.write_text(self._TOML, encoding="utf-8")
        json_path = tmp_path / "plains.json"
        json_path.write_text(json.dumps(self._equivalent_json()), encoding="utf-8")

        toml_cfg = procgen.load_config(str(toml_path))
        json_cfg = procgen.load_config(str(json_path))
        toml_src = procgen.compose_build_script(toml_cfg, "res://out/ts.tres", "samenonce")
        json_src = procgen.compose_build_script(json_cfg, "res://out/ts.tres", "samenonce")
        assert toml_src == json_src

    def test_malformed_json_is_a_clean_config_error(self, tmp_path):
        p = tmp_path / "broken.json"
        p.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(procgen.ConfigError, match="not valid JSON"):
            procgen.load_config(str(p))

    def test_non_object_json_top_level_is_a_clean_config_error(self, tmp_path):
        p = tmp_path / "list.json"
        p.write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(procgen.ConfigError, match="object/table"):
            procgen.load_config(str(p))

    def test_extensionless_path_still_parses_as_toml(self, tmp_path):
        """Back-compat: a path with no recognized extension falls back to the
        historical TOML behavior rather than silently failing."""
        p = tmp_path / "plains_no_ext"
        p.write_text(self._TOML, encoding="utf-8")
        cfg = procgen.load_config(str(p))
        assert cfg["tileset"]["tile_size"] == [8, 8]


class TestConfigValidation:
    def test_minimal_config_valid(self):
        procgen.validate_config(_min_cfg())

    def test_more_than_one_terrain_per_set_errors(self):
        cfg = _min_cfg()
        cfg["terrain_set"] = [
            {"mode": "match_corners_and_sides", "terrains": [{"name": "grass"}, {"name": "sand"}]}
        ]
        with pytest.raises(procgen.ConfigError, match="at most ONE terrain"):
            procgen.validate_config(cfg)

    def test_water_bearing_animation_must_be_default_mode(self):
        cfg = _min_cfg()
        cfg["terrain_set"] = [{"mode": "match_corners_and_sides", "terrains": [{"name": "grass"}]}]
        cfg["terrain_assign"] = [{"atlas": "ground", "strategy": "blob47", "terrain": "grass"}]
        cfg["animation"] = [
            {"atlas": "ground", "base_region": [[0, 0], [0, 0]], "frames": 2, "mode": "random_start"}
        ]
        with pytest.raises(procgen.ConfigError, match="mode='default'"):
            procgen.validate_config(cfg)

    def test_water_bearing_animation_default_mode_ok(self):
        cfg = _min_cfg()
        cfg["terrain_set"] = [{"mode": "match_corners_and_sides", "terrains": [{"name": "grass"}]}]
        cfg["terrain_assign"] = [{"atlas": "ground", "strategy": "blob47", "terrain": "grass"}]
        cfg["animation"] = [
            {"atlas": "ground", "base_region": [[0, 0], [0, 0]], "frames": 2, "mode": "default"}
        ]
        procgen.validate_config(cfg)

    def test_non_water_animation_may_use_random_start(self):
        """Decor animation with NO terrain on its atlas may desync freely."""
        cfg = _min_cfg()
        cfg["animation"] = [
            {"atlas": "ground", "base_region": [[0, 0], [0, 0]], "frames": 3, "mode": "random_start"}
        ]
        procgen.validate_config(cfg)

    def test_non_contiguous_frame_offset_rejected(self):
        """P1-review carry-in: validate_config is the SOLE source of truth for
        the frame_offset contiguity rule (compose_build_script no longer
        re-checks it). A diagonal/other offset must still be rejected here."""
        cfg = _min_cfg()
        cfg["animation"] = [
            {"atlas": "ground", "base_region": [[0, 0], [0, 0]], "frames": 2, "frame_offset": [1, 1]}
        ]
        with pytest.raises(procgen.ConfigError, match="frame_offset must be"):
            procgen.validate_config(cfg)

    def test_unknown_terrain_assign_atlas_errors(self):
        cfg = _min_cfg()
        cfg["terrain_set"] = [{"mode": "match_sides", "terrains": [{"name": "grass"}]}]
        cfg["terrain_assign"] = [{"atlas": "nope", "strategy": "blob47", "terrain": "grass"}]
        with pytest.raises(procgen.ConfigError, match="unknown atlas"):
            procgen.validate_config(cfg)

    def test_unknown_strategy_errors(self):
        cfg = _min_cfg()
        cfg["terrain_set"] = [{"mode": "match_sides", "terrains": [{"name": "grass"}]}]
        cfg["terrain_assign"] = [{"atlas": "ground", "strategy": "wang9", "terrain": "grass"}]
        with pytest.raises(procgen.ConfigError, match="unknown strategy"):
            procgen.validate_config(cfg)

    def test_explicit_scan_needs_tiles(self):
        cfg = _min_cfg()
        cfg["atlas"][0]["scan"] = "explicit"
        with pytest.raises(procgen.ConfigError, match="explicit"):
            procgen.validate_config(cfg)

    def test_minifantasy_edges_interior_param_validates(self):
        """A minifantasy_edges assign with a well-formed `interior` list of
        [col,row] pairs must validate cleanly."""
        cfg = _min_cfg()
        cfg["terrain_set"] = [{"mode": "match_corners", "terrains": [{"name": "grass"}]}]
        cfg["terrain_assign"] = [
            {
                "atlas": "ground",
                "strategy": "minifantasy_edges",
                "terrain": "grass",
                "origin": [25, 3],
                "interior": [[2, 3], [3, 3], [4, 3]],
            }
        ]
        procgen.validate_config(cfg)  # must not raise

    def test_malformed_interior_is_a_clean_config_error(self):
        cfg = _min_cfg()
        cfg["terrain_set"] = [{"mode": "match_corners", "terrains": [{"name": "grass"}]}]
        cfg["terrain_assign"] = [
            {
                "atlas": "ground",
                "strategy": "minifantasy_edges",
                "terrain": "grass",
                "interior": [[2, 3], [3]],  # second entry is not an int pair
            }
        ]
        with pytest.raises(procgen.ConfigError, match="`interior` must be"):
            procgen.validate_config(cfg)

    def test_weighted_interior_form_validates(self):
        """A minifantasy_edges assign whose `interior` mixes bare [col,row] and
        weighted [col,row,weight] entries (positive numbers) must validate."""
        cfg = _min_cfg()
        cfg["terrain_set"] = [{"mode": "match_corners", "terrains": [{"name": "grass"}]}]
        cfg["terrain_assign"] = [
            {
                "atlas": "ground",
                "strategy": "minifantasy_edges",
                "terrain": "grass",
                "origin": [25, 3],
                "interior": [[2, 3, 0.9], [3, 3, 0.05], [4, 3]],  # weighted + weighted + bare
            }
        ]
        procgen.validate_config(cfg)  # must not raise

    def test_non_positive_weight_is_a_clean_config_error(self):
        """A zero or negative weight is a clean ConfigError, not a stack trace."""
        for bad_weight in (0, -0.1, -3):
            cfg = _min_cfg()
            cfg["terrain_set"] = [{"mode": "match_corners", "terrains": [{"name": "grass"}]}]
            cfg["terrain_assign"] = [
                {
                    "atlas": "ground",
                    "strategy": "minifantasy_edges",
                    "terrain": "grass",
                    "interior": [[2, 3, bad_weight]],
                }
            ]
            with pytest.raises(procgen.ConfigError, match="positive number weight"):
                procgen.validate_config(cfg)

    def test_non_numeric_weight_is_a_clean_config_error(self):
        cfg = _min_cfg()
        cfg["terrain_set"] = [{"mode": "match_corners", "terrains": [{"name": "grass"}]}]
        cfg["terrain_assign"] = [
            {
                "atlas": "ground",
                "strategy": "minifantasy_edges",
                "terrain": "grass",
                "interior": [[2, 3, "heavy"]],
            }
        ]
        with pytest.raises(procgen.ConfigError, match="positive number weight"):
            procgen.validate_config(cfg)

    def test_interior_rejected_on_explicit_strategy(self):
        """`interior` is only valid with minifantasy_edges (its full-interior tile
        goes in `tiles` for explicit); reject it rather than silently ignore."""
        cfg = _min_cfg()
        cfg["terrain_set"] = [{"mode": "match_corners", "terrains": [{"name": "grass"}]}]
        cfg["terrain_assign"] = [
            {
                "atlas": "ground",
                "strategy": "explicit",
                "terrain": "grass",
                "tiles": [{"coords": [0, 0], "bits": []}],
                "interior": [[2, 3]],
            }
        ]
        with pytest.raises(procgen.ConfigError, match="only valid with strategy='minifantasy_edges'"):
            procgen.validate_config(cfg)

    def test_interior_rejected_on_blob_strategy(self):
        """`interior` is only for minifantasy_edges (whose 3x5 block omits the
        interior). The blob47/blob16 tables already cover the interior class, so
        `interior` there is nonsensical and must be rejected, not silently applied."""
        for strat in ("blob47", "blob16_sides", "blob16_corners"):
            cfg = _min_cfg()
            cfg["terrain_set"] = [{"mode": "match_corners", "terrains": [{"name": "grass"}]}]
            cfg["terrain_assign"] = [
                {
                    "atlas": "ground",
                    "strategy": strat,
                    "terrain": "grass",
                    "interior": [[2, 3]],
                }
            ]
            with pytest.raises(procgen.ConfigError, match="only valid with strategy='minifantasy_edges'"):
                procgen.validate_config(cfg)

    def test_mixed_atlas_decor_random_start_on_non_terrain_cells_validates(self):
        """P1-hardening finding #2: the water-bearing rule is TILE-level, not
        atlas-level. A single atlas may carry BOTH a terrain-assigned ground
        tile (at (0,0)) AND a random_start decor animation whose base cell
        (5,5) carries no terrain — this must VALIDATE cleanly."""
        cfg = _min_cfg()
        cfg["terrain_set"] = [{"mode": "match_sides", "terrains": [{"name": "grass"}]}]
        cfg["terrain_assign"] = [
            {
                "atlas": "ground",
                "strategy": "explicit",
                "terrain": "grass",
                "tiles": [{"coords": [0, 0], "bits": []}],
            }
        ]
        cfg["animation"] = [
            {"atlas": "ground", "base_region": [[5, 5], [5, 5]], "frames": 3, "mode": "random_start"}
        ]
        procgen.validate_config(cfg)  # must not raise

    def test_random_start_on_a_terrain_bearing_tile_itself_still_errors(self):
        """The same mixed atlas as above, but the animation's base cell IS the
        terrain-assigned cell (0,0) — this must still ERROR, since the
        animated tile itself carries a terrain (water-bearing edges must sync)."""
        cfg = _min_cfg()
        cfg["terrain_set"] = [{"mode": "match_sides", "terrains": [{"name": "grass"}]}]
        cfg["terrain_assign"] = [
            {
                "atlas": "ground",
                "strategy": "explicit",
                "terrain": "grass",
                "tiles": [{"coords": [0, 0], "bits": []}],
            }
        ]
        cfg["animation"] = [
            {"atlas": "ground", "base_region": [[0, 0], [0, 0]], "frames": 3, "mode": "random_start"}
        ]
        with pytest.raises(procgen.ConfigError, match="mode='default'"):
            procgen.validate_config(cfg)

    def test_missing_base_region_is_a_clean_config_error(self):
        """P1-hardening finding #5: a malformed/missing base_region must come
        back as a structured ConfigError from validate_config, never a raw
        Python stack trace from compose-time indexing."""
        cfg = _min_cfg()
        cfg["animation"] = [{"atlas": "ground", "frames": 2}]  # no base_region at all
        with pytest.raises(procgen.ConfigError, match="base_region"):
            procgen.validate_config(cfg)

    def test_malformed_base_region_is_a_clean_config_error(self):
        cfg = _min_cfg()
        cfg["animation"] = [{"atlas": "ground", "base_region": [[0, 0]], "frames": 2}]  # only one corner
        with pytest.raises(procgen.ConfigError, match="base_region"):
            procgen.validate_config(cfg)

    def test_load_config_surfaces_missing_base_region_as_config_error_not_stack_trace(self, tmp_path):
        """End-to-end through load_config (and therefore through
        tileset_build's own try/except ConfigError path): a config with a
        missing base_region must never reach compose_build_script's
        unguarded `(bx0, by0), (bx1, by1) = an["base_region"]` unpack."""
        import json as _json

        cfg = {
            "tileset": {"tile_size": [8, 8]},
            "atlas": [{"id": "ground", "texture": "res://art/ground.png"}],
            "animation": [{"atlas": "ground", "frames": 2}],
        }
        p = tmp_path / "bad_anim.json"
        p.write_text(_json.dumps(cfg), encoding="utf-8")
        with pytest.raises(procgen.ConfigError, match="base_region"):
            procgen.load_config(str(p))

    def test_user_declared_weight_layer_must_be_float(self):
        """`weight` is a RESERVED float layer (the build<->audit<->matcher
        per-variant weighting contract). A config that declares its own
        `weight` custom-data layer with any other type must fail validation
        with a clean ConfigError naming `weight` as reserved, rather than
        silently letting a mistyped layer through and breaking weight reads
        later at audit time."""
        cfg = _min_cfg()
        cfg["custom_data"] = {"layers": [{"name": "weight", "type": "string"}]}
        with pytest.raises(procgen.ConfigError, match="'weight' is reserved"):
            procgen.validate_config(cfg)

    def test_user_declared_weight_layer_as_float_validates(self):
        cfg = _min_cfg()
        cfg["custom_data"] = {"layers": [{"name": "weight", "type": "float"}]}
        procgen.validate_config(cfg)  # must not raise


# --- GDScript composition ---------------------------------------------------


class TestComposeBuildScript:
    def test_script_extends_scenetree_and_quits(self):
        cfg = procgen.validate_config(_min_cfg())
        src = procgen.compose_build_script(cfg, "res://out/ts.tres", "abc123")
        assert src.lstrip().startswith("extends SceneTree")
        assert "quit(" in src

    def test_op_order_terrain_set_before_terrain_and_bits(self):
        """The load-bearing order: td.terrain_set is assigned before td.terrain,
        which is assigned before any set_terrain_peering_bit call."""
        cfg = _min_cfg()
        cfg["terrain_set"] = [{"mode": "match_corners_and_sides", "terrains": [{"name": "grass"}]}]
        cfg["terrain_assign"] = [{"atlas": "ground", "strategy": "blob47", "terrain": "grass"}]
        cfg = procgen.validate_config(cfg)
        src = procgen.compose_build_script(cfg, "res://out/ts.tres", "n0")
        i_set = src.index("td.terrain_set =")
        i_terr = src.index("td.terrain =")
        i_bits = src.index("set_terrain_peering_bit")
        assert i_set < i_terr < i_bits

    def test_reserved_regions_computed_before_scan_in_script(self):
        src = procgen.compose_build_script(procgen.validate_config(_min_cfg()), "res://o.tres", "n1")
        i_reserve = src.index("RESERVE animation frame regions FIRST")
        i_scan = src.index("Collect base cells to create")
        assert i_reserve < i_scan

    def test_save_then_reload_present(self):
        src = procgen.compose_build_script(procgen.validate_config(_min_cfg()), "res://o.tres", "n2")
        i_save = src.index("ResourceSaver.save")
        i_reload = src.index("ResourceLoader.load")
        assert i_save < i_reload

    def test_explicit_strategy_bits_flow_into_plan(self):
        cfg = _min_cfg()
        cfg["terrain_set"] = [{"mode": "match_sides", "terrains": [{"name": "grass"}]}]
        cfg["terrain_assign"] = [
            {
                "atlas": "ground",
                "strategy": "explicit",
                "terrain": "grass",
                "tiles": [{"coords": [2, 3], "bits": ["TOP_SIDE", "LEFT_SIDE"]}],
            }
        ]
        cfg = procgen.validate_config(cfg)
        src = procgen.compose_build_script(cfg, "res://o.tres", "n3")
        assert "2,3" in src
        assert "TOP_SIDE" in src


def _plan_from_source(src: str) -> dict:
    """Extract the resolved plan dict compose_build_script embeds as the
    PLAN_JSON string literal. The script line is `const PLAN_JSON := "<json>"`
    where the json is a json.dumps'd python-repr'd string; peel both layers."""
    import json as _json

    marker = "const PLAN_JSON := "
    line = next(ln for ln in src.splitlines() if ln.startswith(marker))
    outer = _json.loads(line[len(marker):])  # the GDScript string literal -> the inner json text
    return _json.loads(outer)


def _weighted_interior_cfg() -> dict:
    cfg = _min_cfg()
    cfg["terrain_set"] = [{"mode": "match_corners", "terrains": [{"name": "grass"}]}]
    cfg["terrain_assign"] = [
        {
            "atlas": "ground",
            "strategy": "minifantasy_edges",
            "terrain": "grass",
            "origin": [0, 0],
            "interior": [[3, 0, 0.9], [4, 0, 0.05], [5, 0, 0.05]],
        }
    ]
    return procgen.validate_config(cfg)


class TestComposeBuildWeighting:
    """Weights flow config -> plan -> per-tile `weight` custom-data layer. The
    layer is baked ONLY when some tile carries an explicit weight, is auto-added
    as TYPE_FLOAT, and never clobbers a user-declared `weight` layer."""

    def test_unweighted_config_bakes_no_weight_layer(self):
        cfg = _min_cfg()
        cfg["terrain_set"] = [{"mode": "match_corners", "terrains": [{"name": "grass"}]}]
        cfg["terrain_assign"] = [
            {"atlas": "ground", "strategy": "minifantasy_edges", "terrain": "grass", "origin": [0, 0], "interior": [[3, 0]]}
        ]
        cfg = procgen.validate_config(cfg)
        plan = _plan_from_source(procgen.compose_build_script(cfg, "res://o.tres", "nw"))
        assert plan["weight_layer_index"] == -1
        assert all(cd["name"] != "weight" for cd in plan["custom_data"])
        # no assign carries a baked weight when the layer is inactive
        for atlas in plan["atlases"]:
            for cell in atlas["assign"].values():
                assert "weight" not in cell

    def test_weighted_config_auto_adds_float_weight_layer(self):
        plan = _plan_from_source(procgen.compose_build_script(_weighted_interior_cfg(), "res://o.tres", "nw"))
        assert plan["weight_layer_index"] == 0  # first (only) custom-data layer
        assert plan["custom_data"][0] == {"name": "weight", "type": "TYPE_FLOAT"}

    def test_weighted_config_bakes_every_terrain_tile_a_weight(self):
        """With the layer active, EVERY terrain-bearing tile gets a float — the
        explicit weight for named cells, _DEFAULT_WEIGHT for the rest — so the
        layer is fully populated and the audit reads a real value off each."""
        plan = _plan_from_source(procgen.compose_build_script(_weighted_interior_cfg(), "res://o.tres", "nw"))
        assign = plan["atlases"][0]["assign"]
        # the three named interior cells carry their explicit weights
        assert assign["3,0"]["weight"] == 0.9
        assert assign["4,0"]["weight"] == 0.05
        assert assign["5,0"]["weight"] == 0.05
        # every other terrain-bearing tile (the 15 edge cells) defaults to 1.0
        assert all("weight" in cell for cell in assign.values())
        assert assign["1,1"]["weight"] == 1.0  # water-center edge cell, default weight

    def test_user_declared_weight_layer_is_not_clobbered(self):
        """If the config already declares a `weight` custom-data layer, reuse its
        index rather than appending a duplicate — the layer bookkeeping must not
        double-add or shift the user's layer."""
        cfg = _min_cfg()
        cfg["terrain_set"] = [{"mode": "match_corners", "terrains": [{"name": "grass"}]}]
        cfg["custom_data"] = {"layers": [{"name": "biome_id", "type": "string"}, {"name": "weight", "type": "float"}]}
        cfg["terrain_assign"] = [
            {
                "atlas": "ground",
                "strategy": "minifantasy_edges",
                "terrain": "grass",
                "origin": [0, 0],
                "interior": [[3, 0, 0.9]],
            }
        ]
        cfg = procgen.validate_config(cfg)
        plan = _plan_from_source(procgen.compose_build_script(cfg, "res://o.tres", "nw"))
        names = [cd["name"] for cd in plan["custom_data"]]
        assert names == ["biome_id", "weight"]  # no duplicate appended
        assert plan["weight_layer_index"] == 1  # the user's existing weight layer
        assert plan["atlases"][0]["assign"]["3,0"]["weight"] == 0.9

    def test_user_declared_weight_layer_with_no_explicit_weights_is_still_fully_populated(self):
        """The population gap this test locks: a config that declares its own
        float `weight` custom-data layer but gives NO explicit interior weights
        must still bake a weight into EVERY terrain-bearing tile (all 1.0) —
        the trigger for populating is "the weight layer exists", not "some
        explicit non-default weight was given". Without this, a user-declared
        but unpopulated `weight` layer would read back as garbage at audit
        time instead of a clean 1.0 default."""
        cfg = _min_cfg()
        cfg["terrain_set"] = [{"mode": "match_corners", "terrains": [{"name": "grass"}]}]
        cfg["custom_data"] = {"layers": [{"name": "weight", "type": "float"}]}
        cfg["terrain_assign"] = [
            {
                "atlas": "ground",
                "strategy": "minifantasy_edges",
                "terrain": "grass",
                "origin": [0, 0],
                "interior": [[3, 0]],  # bare cell, no explicit weight anywhere in this config
            }
        ]
        cfg = procgen.validate_config(cfg)
        plan = _plan_from_source(procgen.compose_build_script(cfg, "res://o.tres", "nw"))
        assert plan["weight_layer_index"] == 0  # the user's declared layer, reused not duplicated
        assert plan["custom_data"] == [{"name": "weight", "type": "TYPE_FLOAT"}]
        assign = plan["atlases"][0]["assign"]
        assert assign, "expected at least one terrain-bearing tile"
        assert all(cell["weight"] == 1.0 for cell in assign.values()), assign
