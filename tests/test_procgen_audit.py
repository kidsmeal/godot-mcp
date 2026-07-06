"""Offline tests for the procgen module (Phase 2: terrain_audit).

No real Godot binary required — these exercise the pure-Python surface:
expected-signature derivation (proving it comes from the mode's valid-bit
enumeration, not a hardcoded count), the raw-dump -> coverage/report builder
(`_audit_report`/`_format_audit_report`), and the composed GDScript's shape.
The live headless audit (built via procgen_tileset_build, then audited) is
covered by test_procgen_audit_build.py (skipped when Godot is unavailable).
"""
from __future__ import annotations

from godot_mcp import procgen

# --- expected_signature_set: derived from mode, not hardcoded ---------------


class TestExpectedSignatureSet:
    def test_match_corners_and_sides_count_matches_blob47_table_size(self):
        """The count is `len(blob47_table())`, not a literal 47 anywhere in
        the signature-computation path — this proves it by construction:
        expected_signature_set and blob47_table share the same source data."""
        expected = procgen.expected_signature_set("MATCH_CORNERS_AND_SIDES")
        assert len(expected) == len(procgen.blob47_table())
        assert len(expected) == 47  # documents the derived value, does not assert it directly

    def test_match_sides_count_matches_blob16_sides_table_size(self):
        expected = procgen.expected_signature_set("MATCH_SIDES")
        assert len(expected) == len(procgen.blob16_sides_table())
        assert len(expected) == 16

    def test_match_corners_count_matches_blob16_corners_table_size(self):
        expected = procgen.expected_signature_set("MATCH_CORNERS")
        assert len(expected) == len(procgen.blob16_corners_table())
        assert len(expected) == 16

    def test_signatures_are_frozensets_of_bit_names_from_the_tables(self):
        """Every expected signature for MATCH_SIDES is drawn straight from the
        blob16_sides_table's bit-name values (side bits only, no corners)."""
        expected = procgen.expected_signature_set("MATCH_SIDES")
        allowed = {"TOP_SIDE", "RIGHT_SIDE", "BOTTOM_SIDE", "LEFT_SIDE"}
        for sig in expected:
            assert sig <= allowed

    def test_isolated_and_full_interior_classes_present(self):
        expected = procgen.expected_signature_set("MATCH_CORNERS_AND_SIDES")
        assert frozenset() in expected  # isolated tile, no neighbors
        assert frozenset({
            "TOP_SIDE", "RIGHT_SIDE", "BOTTOM_SIDE", "LEFT_SIDE",
            "TOP_RIGHT_CORNER", "BOTTOM_RIGHT_CORNER", "BOTTOM_LEFT_CORNER", "TOP_LEFT_CORNER",
        }) in expected

    def test_unknown_mode_raises(self):
        import pytest
        with pytest.raises(ValueError, match="unknown terrain set mode"):
            procgen.expected_signature_set("MATCH_WANG9")


# --- _sig_key ----------------------------------------------------------------


class TestSigKey:
    def test_empty_bits_is_empty_string(self):
        assert procgen._sig_key([]) == ""

    def test_sorted_regardless_of_input_order(self):
        assert procgen._sig_key(["LEFT_SIDE", "TOP_SIDE"]) == procgen._sig_key(["TOP_SIDE", "LEFT_SIDE"])
        assert procgen._sig_key(["TOP_SIDE", "LEFT_SIDE"]) == "LEFT_SIDE,TOP_SIDE"


# --- raw-dump fixtures --------------------------------------------------------


def _tile(source_id=0, coords=(0, 0), terrain_set=0, terrain=0, bits=None, custom_data=False, animation=None, weight=None):
    tile = {
        "source_id": source_id,
        "coords": list(coords),
        "terrain_set": terrain_set,
        "terrain": terrain,
        "bits": bits or [],
        "custom_data": custom_data,
        "animation": animation,
    }
    # A real GDScript dump always carries "weight"; leaving it off here (weight=None)
    # exercises _audit_report's default-to-1.0 fallback for older/synthetic dumps.
    if weight is not None:
        tile["weight"] = weight
    return tile


def _terrain_set(index=0, mode="MATCH_SIDES", terrains=None):
    return {"index": index, "mode": mode, "terrains": terrains if terrains is not None else [{"index": 0, "name": "grass"}]}


def _all_sides_tiles(terrain_set=0, terrain=0, source_id=0):
    """One tile per MATCH_SIDES signature class (all 16), so a full sheet is
    complete-by-default; individual tests remove/duplicate specific tiles."""
    tiles = []
    table = procgen.blob16_sides_table()
    for i, ((col, row), bits) in enumerate(table.items()):
        tiles.append(_tile(source_id=source_id, coords=(col, row), terrain_set=terrain_set, terrain=terrain, bits=bits))
    return tiles


# --- _audit_report: coverage / missing / duplicated ---------------------------


class TestAuditReportCoverage:
    def test_complete_sheet_reports_clean(self):
        dump = {"ok": True, "terrain_sets": [_terrain_set()], "tiles": _all_sides_tiles()}
        report = procgen._audit_report(dump, terrain_set=-1)
        assert report["ok"] is True
        assert report["errors"] == []
        cov = report["coverage"]["0"]
        assert cov["expected_count"] == 16
        assert cov["covered_count"] == 16
        assert cov["missing"] == []

    def test_missing_signature_combo_is_caught(self):
        """A fixture with a deliberately MISSING signature combo (the
        all-four-sides tile removed) is caught as `missing`."""
        tiles = _all_sides_tiles()
        full_key = procgen._sig_key(["TOP_SIDE", "RIGHT_SIDE", "BOTTOM_SIDE", "LEFT_SIDE"])
        tiles = [t for t in tiles if procgen._sig_key(t["bits"]) != full_key]
        dump = {"ok": True, "terrain_sets": [_terrain_set()], "tiles": tiles}
        report = procgen._audit_report(dump, terrain_set=-1)
        cov = report["coverage"]["0"]
        assert full_key in cov["missing"]
        assert cov["covered_count"] == 15

    def test_duplicated_signature_is_a_variant_not_an_error(self):
        """Two tiles sharing one signature is ALLOWED — flagged as a variant,
        never an error (the matcher's seeded pick consumes variants)."""
        tiles = _all_sides_tiles()
        # duplicate the isolated-tile (no bits) signature at a new coord
        tiles.append(_tile(coords=(9, 9), terrain_set=0, terrain=0, bits=[]))
        dump = {"ok": True, "terrain_sets": [_terrain_set()], "tiles": tiles}
        report = procgen._audit_report(dump, terrain_set=-1)
        assert report["errors"] == []  # variants are not errors
        cov = report["coverage"]["0"]
        assert "" in cov["variants"]
        assert len(cov["variants"][""]) == 2

    def test_scoping_to_one_terrain_set_only_reports_that_set(self):
        tiles = _all_sides_tiles(terrain_set=0) + _all_sides_tiles(terrain_set=1, source_id=1)
        dump = {
            "ok": True,
            "terrain_sets": [_terrain_set(0, terrains=[{"index": 0, "name": "grass"}]), _terrain_set(1, terrains=[{"index": 0, "name": "sand"}])],
            "tiles": tiles,
        }
        report = procgen._audit_report(dump, terrain_set=1)
        assert list(report["coverage"].keys()) == ["1"]
        assert report["coverage"]["1"]["terrain_name"] == "sand"

    def test_unknown_terrain_set_index_errors(self):
        dump = {"ok": True, "terrain_sets": [_terrain_set()], "tiles": _all_sides_tiles()}
        report = procgen._audit_report(dump, terrain_set=5)
        assert report["ok"] is False
        assert "does not exist" in report["error"]


# --- _audit_report: broken ordering / law violation / unused ------------------


class TestAuditReportDataIntegrity:
    def test_broken_ordering_tile_is_caught(self):
        """terrain != -1 but terrain_set == -1 is broken ordering."""
        tiles = _all_sides_tiles()
        tiles.append(_tile(coords=(20, 20), terrain_set=-1, terrain=0, bits=[]))
        dump = {"ok": True, "terrain_sets": [_terrain_set()], "tiles": tiles}
        report = procgen._audit_report(dump, terrain_set=-1)
        assert any("broken ordering" in e for e in report["errors"])
        assert len(report["broken_ordering"]) == 1
        assert report["broken_ordering"][0]["coords"] == [20, 20]

    def test_more_than_one_terrain_per_set_errors(self):
        dump = {
            "ok": True,
            "terrain_sets": [_terrain_set(terrains=[{"index": 0, "name": "grass"}, {"index": 1, "name": "sand"}])],
            "tiles": _all_sides_tiles(),
        }
        report = procgen._audit_report(dump, terrain_set=-1)
        assert any("water-bottom law violation" in e for e in report["errors"])

    def test_law_violation_in_unscoped_set_is_still_caught(self):
        """The >1-terrain-per-set check is NOT scope-limited (docstring):
        auditing terrain_set=0 must still catch a violation that lives in a
        DIFFERENT terrain_set (1) that the caller did not ask to focus on."""
        tiles = _all_sides_tiles(terrain_set=0) + _all_sides_tiles(terrain_set=1, source_id=1)
        dump = {
            "ok": True,
            "terrain_sets": [
                _terrain_set(0, terrains=[{"index": 0, "name": "grass"}]),
                _terrain_set(1, terrains=[{"index": 0, "name": "sand"}, {"index": 1, "name": "silt"}]),
            ],
            "tiles": tiles,
        }
        report = procgen._audit_report(dump, terrain_set=0)
        assert any("water-bottom law violation" in e for e in report["errors"])
        assert any("terrain_set 1" in e for e in report["errors"])
        # coverage table itself stays scoped to the requested set only
        assert list(report["coverage"].keys()) == ["0"]

    def test_unused_tile_is_reported(self):
        tiles = _all_sides_tiles()
        tiles.append(_tile(coords=(21, 21), terrain_set=-1, terrain=-1, bits=[], custom_data=False))
        dump = {"ok": True, "terrain_sets": [_terrain_set()], "tiles": tiles}
        report = procgen._audit_report(dump, terrain_set=-1)
        assert any(u["coords"] == [21, 21] for u in report["unused_tiles"])

    def test_tile_with_custom_data_is_not_unused(self):
        tiles = _all_sides_tiles()
        tiles.append(_tile(coords=(22, 22), terrain_set=-1, terrain=-1, bits=[], custom_data=True))
        dump = {"ok": True, "terrain_sets": [_terrain_set()], "tiles": tiles}
        report = procgen._audit_report(dump, terrain_set=-1)
        assert not any(u["coords"] == [22, 22] for u in report["unused_tiles"])


# --- _audit_report: animation sync lint ---------------------------------------


class TestAuditReportAnimationSync:
    def _anim(self, frames=2, durations=(0.5, 0.5), mode="DEFAULT"):
        return {"frames": frames, "durations": list(durations), "mode": mode}

    def test_synced_default_animated_tiles_are_clean(self):
        tiles = [
            _tile(coords=(0, 0), bits=[], animation=self._anim()),
            _tile(coords=(1, 0), bits=["TOP_SIDE"], animation=self._anim()),
        ]
        dump = {"ok": True, "terrain_sets": [_terrain_set()], "tiles": tiles}
        report = procgen._audit_report(dump, terrain_set=-1)
        assert not any("desync" in e for e in report["errors"])

    def test_desynced_duration_is_an_error_not_a_warning(self):
        """A random-start / desynced water tile desyncs coastlines: error."""
        tiles = [
            _tile(coords=(0, 0), bits=[], animation=self._anim(durations=(0.5, 0.5))),
            _tile(coords=(1, 0), bits=["TOP_SIDE"], animation=self._anim(durations=(0.3, 0.3))),
        ]
        dump = {"ok": True, "terrain_sets": [_terrain_set()], "tiles": tiles}
        report = procgen._audit_report(dump, terrain_set=-1)
        assert any("desync" in e for e in report["errors"])

    def test_random_start_mode_is_an_error(self):
        tiles = [
            _tile(coords=(0, 0), bits=[], animation=self._anim(mode="DEFAULT")),
            _tile(coords=(1, 0), bits=["TOP_SIDE"], animation=self._anim(mode="RANDOM_START_TIMES")),
        ]
        dump = {"ok": True, "terrain_sets": [_terrain_set()], "tiles": tiles}
        report = procgen._audit_report(dump, terrain_set=-1)
        assert any("desync" in e for e in report["errors"])

    def test_non_terrain_animated_decor_tile_is_not_linted(self):
        """A tile with terrain == -1 (decor, no terrain) never enters the
        water-bearing animation-sync check, regardless of its own mode."""
        tiles = [
            _tile(coords=(0, 0), terrain=0, bits=[], animation=self._anim(mode="DEFAULT")),
            _tile(coords=(5, 5), terrain=-1, terrain_set=-1, bits=[], animation=self._anim(mode="RANDOM_START_TIMES")),
        ]
        dump = {"ok": True, "terrain_sets": [_terrain_set()], "tiles": tiles}
        report = procgen._audit_report(dump, terrain_set=-1)
        assert not any("desync" in e for e in report["errors"])


# --- report load failure + formatting -----------------------------------------


class TestAuditReportLoadFailureAndFormatting:
    def test_load_failure_propagates(self):
        report = procgen._audit_report({"ok": False, "error": "could not load TileSet"}, terrain_set=-1)
        assert report["ok"] is False
        assert "could not load" in report["error"]

    def test_format_reports_error_string(self):
        text = procgen._format_audit_report({"ok": False, "error": "boom"}, "res://x.tres")
        assert text.startswith("ERROR")
        assert "boom" in text

    def test_format_clean_report_says_clean(self):
        dump = {"ok": True, "terrain_sets": [_terrain_set()], "tiles": _all_sides_tiles()}
        report = procgen._audit_report(dump, terrain_set=-1)
        text = procgen._format_audit_report(report, "res://ts.tres")
        assert "CLEAN" in text
        assert "res://ts.tres" in text

    def test_format_includes_coverage_table_row(self):
        dump = {"ok": True, "terrain_sets": [_terrain_set()], "tiles": _all_sides_tiles()}
        report = procgen._audit_report(dump, terrain_set=-1)
        text = procgen._format_audit_report(report, "res://ts.tres")
        assert "| 0 | grass | MATCH_SIDES | 16 | 16 | 0 | 0 |" in text

    def test_format_embeds_machine_coverage_json_block(self):
        """The returned string must carry BOTH the markdown table (for
        humans) AND the machine `coverage` dict (for the in-house matcher),
        as a fenced json block a consumer can parse back out."""
        import json

        dump = {"ok": True, "terrain_sets": [_terrain_set()], "tiles": _all_sides_tiles()}
        report = procgen._audit_report(dump, terrain_set=-1)
        text = procgen._format_audit_report(report, "res://ts.tres")

        assert "```json" in text
        fenced = text.split("```json", 1)[1].split("```", 1)[0]
        parsed = json.loads(fenced)
        assert parsed == report["coverage"]
        cov = parsed["0"]
        assert set(cov.keys()) == {
            "mode", "terrain_name", "expected_count", "covered_count", "missing", "variants", "signatures",
        }


# --- coverage dict shape (documented in terrain_audit's docstring) -----------


class TestCoverageDictShape:
    """Asserts the coverage dict has exactly the keys terrain_audit's
    docstring documents — the game-repo matcher depends on this shape."""

    def test_coverage_entry_has_documented_keys(self):
        dump = {"ok": True, "terrain_sets": [_terrain_set()], "tiles": _all_sides_tiles()}
        report = procgen._audit_report(dump, terrain_set=-1)
        cov = report["coverage"]["0"]
        assert set(cov.keys()) == {
            "mode", "terrain_name", "expected_count", "covered_count", "missing", "variants", "signatures",
        }

    def test_signatures_dict_maps_key_to_list_of_tile_dicts(self):
        dump = {"ok": True, "terrain_sets": [_terrain_set()], "tiles": _all_sides_tiles()}
        report = procgen._audit_report(dump, terrain_set=-1)
        cov = report["coverage"]["0"]
        for _key, tiles in cov["signatures"].items():
            assert isinstance(tiles, list)
            for t in tiles:
                assert set(t.keys()) == {"source_id", "coords", "weight"}

    def test_tile_dict_weight_defaults_to_1_when_dump_omits_it(self):
        """A dump without per-tile "weight" (unweighted tileset / older dump)
        must still yield a usable relative weight of 1.0 in every tile dict, so
        the matcher's normalization never divides by a missing key."""
        dump = {"ok": True, "terrain_sets": [_terrain_set()], "tiles": _all_sides_tiles()}
        report = procgen._audit_report(dump, terrain_set=-1)
        cov = report["coverage"]["0"]
        for tiles in cov["signatures"].values():
            for t in tiles:
                assert t["weight"] == 1.0

    def test_tile_dict_carries_explicit_weight_from_dump(self):
        """When the dump provides a per-tile weight (a weighted build), it must
        flow through into the coverage tile dict unchanged."""
        tiles = _all_sides_tiles()
        tiles[0]["weight"] = 0.9
        tiles[1]["weight"] = 0.05
        dump = {"ok": True, "terrain_sets": [_terrain_set()], "tiles": tiles}
        report = procgen._audit_report(dump, terrain_set=-1)
        sigs = report["coverage"]["0"]["signatures"]
        by_coords = {tuple(t["coords"]): t["weight"] for lst in sigs.values() for t in lst}
        assert by_coords[tuple(tiles[0]["coords"])] == 0.9
        assert by_coords[tuple(tiles[1]["coords"])] == 0.05

    def test_top_level_report_has_documented_keys(self):
        dump = {"ok": True, "terrain_sets": [_terrain_set()], "tiles": _all_sides_tiles()}
        report = procgen._audit_report(dump, terrain_set=-1)
        assert set(report.keys()) == {
            "ok", "errors", "warnings", "coverage", "unused_tiles", "broken_ordering", "tile_count", "terrain_set_count",
        }


# --- GDScript composition -----------------------------------------------------


class TestComposeAuditScript:
    def test_script_extends_scenetree_and_quits(self):
        src = procgen.compose_audit_script("res://ts.tres", "abc123")
        assert src.lstrip().startswith("extends SceneTree")
        assert "quit(" in src

    def test_script_references_tileset_path_and_sentinels(self):
        src = procgen.compose_audit_script("res://tilesets/plains.tres", "n0")
        assert "res://tilesets/plains.tres" in src
        assert "PROCGEN_JSON_BEGIN:n0" in src
        assert "PROCGEN_JSON_END:n0" in src

    def test_script_queries_valid_terrain_peering_bit_before_reading(self):
        """The dump must gate on is_valid_terrain_peering_bit so it works for
        any mode without GDScript-side branching on mode."""
        src = procgen.compose_audit_script("res://ts.tres", "n1")
        assert "is_valid_terrain_peering_bit" in src
        i_valid = src.index("is_valid_terrain_peering_bit")
        i_get = src.index("get_terrain_peering_bit(bit)")
        assert i_valid < i_get
