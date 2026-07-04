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

    def test_corners_table_has_16_entries_corner_bits_only(self):
        table = procgen.blob16_corners_table()
        assert len(table) == 16
        allowed = {"TOP_CORNER", "RIGHT_CORNER", "BOTTOM_CORNER", "LEFT_CORNER"}
        for bits in table.values():
            assert set(bits) <= allowed

    def test_sides_empty_and_full(self):
        table = procgen.blob16_sides_table(width=4)
        assert table[(0, 0)] == []  # mask 0
        assert set(table[(3, 3)]) == {"TOP_SIDE", "RIGHT_SIDE", "BOTTOM_SIDE", "LEFT_SIDE"}  # mask 15


# --- config validation ------------------------------------------------------


def _min_cfg() -> dict:
    return {
        "tileset": {"tile_size": [8, 8]},
        "atlas": [{"id": "ground", "texture": "res://art/ground.png", "scan": "non_transparent"}],
    }


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
