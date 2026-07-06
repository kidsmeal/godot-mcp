"""Golden-file live test for procgen_terrain_audit.

Binary-gated: skipped when no Godot binary resolves. Builds a tiny SYNTHETIC
TileSet with procgen_tileset_build (a real Phase-1 build, not a hand-authored
.tres) using the 'explicit' terrain-assign strategy, then runs the real
terrain_audit end to end: once against a complete 16-signature sheet (must
report clean), once against a deliberately incomplete sheet (must report the
exact missing count), and once against a hand-text-patched .tres carrying a
second terrain in one terrain_set (water-bottom law violation). The
broken-ordering fixture (terrain != -1, terrain_set == -1) is exercised via a
synthetic raw dump in the offline test_procgen_audit.py instead — see the
docstring on test_more_than_one_terrain_per_set_caught_on_real_tres for why
that state cannot be produced through any real engine load path.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from godot_mcp import config, procgen, runner

_godot_available = bool(config.resolve_godot() and Path(config.resolve_godot()[0]).exists())

# 4x4 opaque grid (32x32 px at 8x8 tiles) — enough cells to place a handful of
# explicit MATCH_SIDES tiles plus a couple of spares for broken-ordering probes.
_MAKE_FIXTURE = r"""extends SceneTree
func _initialize() -> void:
	var w := 32
	var h := 32
	var img := Image.create(w, h, false, Image.FORMAT_RGBA8)
	img.fill(Color(0, 0, 0, 0))
	for gy in range(4):
		for gx in range(4):
			_fill_cell(img, gx, gy, Color(0.3, 0.6, 0.2, 1.0))
	var err := img.save_png(OS.get_environment("PROCGEN_FIXTURE_OUT"))
	print("FIXTURE_SAVE_RC=" + str(err))
	quit(0)

func _fill_cell(img: Image, gx: int, gy: int, col: Color) -> void:
	for py in range(8):
		for px in range(8):
			img.set_pixel(gx * 8 + px, gy * 8 + py, col)
"""


@pytest.mark.skipif(not _godot_available, reason="Godot binary not resolvable on this machine")
class TestTerrainAuditGolden:
    @pytest.fixture()
    def tmp_project(self, tmp_path_factory, monkeypatch):
        proj = tmp_path_factory.mktemp("procgen_audit_proj")
        (proj / "project.godot").write_text(
            'config_version=5\n\n[application]\nconfig/name="ProcgenAuditFixture"\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(config, "PROJECT_ROOT", proj)
        return proj

    def _make_fixture_atlas(self, proj: Path, monkeypatch) -> str:
        art = proj / "art"
        art.mkdir(parents=True, exist_ok=True)
        out_png = art / "fixture.png"
        monkeypatch.setenv("PROCGEN_FIXTURE_OUT", str(out_png))
        r = runner.run_temp_probe(_MAKE_FIXTURE, timeout=60)
        assert r.get("rc") == 0, f"fixture generation failed: {r}"
        assert out_png.exists(), f"fixture PNG not written: {r.get('out')}"
        return "res://art/fixture.png"

    def _complete_config(self, tmp_path: Path, texture_res: str) -> str:
        """Explicit strategy covering ALL 16 MATCH_SIDES classes — one tile
        per class, laid out on the 4x4 fixture grid — so the audit of a
        cleanly-built tileset should report zero missing/broken/errors."""
        table = procgen.blob16_sides_table(width=4)
        tiles_toml = ",\n".join(
            f'  {{ coords = [{col}, {row}], bits = {bits!r} }}'.replace("'", '"')
            for (col, row), bits in table.items()
        )
        cfg = f"""
[tileset]
tile_size = [8, 8]

[[atlas]]
id = "ground"
texture = "{texture_res}"
scan = "all"

[[terrain_set]]
mode = "match_sides"
terrains = [ {{ name = "grass", color = "#4c8f3c" }} ]

[[terrain_assign]]
atlas = "ground"
strategy = "explicit"
terrain = "grass"
tiles = [
{tiles_toml}
]
"""
        p = tmp_path / "complete.toml"
        p.write_text(cfg, encoding="utf-8")
        return str(p)

    def _corners_complete_config(self, tmp_path: Path, texture_res: str) -> str:
        """strategy='blob16_corners' covering all 16 MATCH_CORNERS classes —
        the regression the P3 S1 spike surfaced: this strategy used to emit
        the axis-aligned CORNER bits (hex/iso-only), which
        `is_valid_terrain_peering_bit` rejects on a square grid, so the built
        tileset audited as all-isolated (0/16 covered). Uses the real
        strategy path (not 'explicit') so a regression here is caught again."""
        cfg = f"""
[tileset]
tile_size = [8, 8]

[[atlas]]
id = "ground"
texture = "{texture_res}"
scan = "all"

[[terrain_set]]
mode = "match_corners"
terrains = [ {{ name = "grass", color = "#4c8f3c" }} ]

[[terrain_assign]]
atlas = "ground"
strategy = "blob16_corners"
terrain = "grass"
"""
        p = tmp_path / "corners_complete.toml"
        p.write_text(cfg, encoding="utf-8")
        return str(p)

    def _incomplete_config(self, tmp_path: Path, texture_res: str) -> str:
        """Explicit strategy covering only 3 of the 16 MATCH_SIDES classes —
        a deliberately incomplete fixture the audit must catch as `missing`."""
        table = procgen.blob16_sides_table(width=4)
        keep = list(table.items())[:3]
        tiles_toml = ",\n".join(
            f'  {{ coords = [{col}, {row}], bits = {bits!r} }}'.replace("'", '"')
            for (col, row), bits in keep
        )
        cfg = f"""
[tileset]
tile_size = [8, 8]

[[atlas]]
id = "ground"
texture = "{texture_res}"
scan = "all"

[[terrain_set]]
mode = "match_sides"
terrains = [ {{ name = "grass", color = "#4c8f3c" }} ]

[[terrain_assign]]
atlas = "ground"
strategy = "explicit"
terrain = "grass"
tiles = [
{tiles_toml}
]
"""
        p = tmp_path / "incomplete.toml"
        p.write_text(cfg, encoding="utf-8")
        return str(p)

    def _two_terrain_set_config(self, tmp_path: Path, texture_res: str) -> str:
        """Two valid (one-terrain-each, at build time) terrain sets sharing
        the same atlas — terrain_set 0 = grass (complete 16-signature sheet),
        terrain_set 1 = sand (declared but left untiled here; a second
        terrain is hand-text-patched onto it after the build, since
        tileset_build itself refuses >1 terrain per set before ever
        launching Godot)."""
        table = procgen.blob16_sides_table(width=4)
        tiles_toml = ",\n".join(
            f'  {{ coords = [{col}, {row}], bits = {bits!r} }}'.replace("'", '"')
            for (col, row), bits in table.items()
        )
        cfg = f"""
[tileset]
tile_size = [8, 8]

[[atlas]]
id = "ground"
texture = "{texture_res}"
scan = "all"

[[terrain_set]]
mode = "match_sides"
terrains = [ {{ name = "grass", color = "#4c8f3c" }} ]

[[terrain_set]]
mode = "match_sides"
terrains = [ {{ name = "sand", color = "#e0c080" }} ]

[[terrain_assign]]
atlas = "ground"
strategy = "explicit"
terrain = "grass"
tiles = [
{tiles_toml}
]
"""
        p = tmp_path / "two_sets.toml"
        p.write_text(cfg, encoding="utf-8")
        return str(p)

    def test_blob16_corners_strategy_audits_clean(self, tmp_project, tmp_path, monkeypatch):
        """Regression test for the P3 S1 carry-in bug: strategy='blob16_corners'
        must build a tileset carrying the DIAGONAL corner bits, so the audit
        reports full 16/16 coverage — not 0/16 (all-isolated), which is what
        the axis-aligned-bit bug produced."""
        texture_res = self._make_fixture_atlas(tmp_project, monkeypatch)
        cfg_path = self._corners_complete_config(tmp_path, texture_res)
        build_result = procgen.tileset_build(cfg_path, "res://tilesets/corners_complete.tres")
        assert build_result.startswith("OK"), build_result

        audit_result = procgen.terrain_audit("res://tilesets/corners_complete.tres")
        assert "CLEAN" in audit_result, audit_result
        assert "ERROR" not in audit_result.split("\n")[0], audit_result
        assert "| 0 | grass | MATCH_CORNERS | 16 | 16 | 0 | 0 |" in audit_result, audit_result

        fenced = audit_result.split("```json", 1)[1].split("```", 1)[0]
        coverage = json.loads(fenced)
        cov = coverage["0"]
        assert cov["mode"] == "MATCH_CORNERS"
        assert cov["expected_count"] == 16
        assert cov["covered_count"] == 16
        assert cov["missing"] == []

    def test_clean_tileset_audits_clean(self, tmp_project, tmp_path, monkeypatch):
        texture_res = self._make_fixture_atlas(tmp_project, monkeypatch)
        cfg_path = self._complete_config(tmp_path, texture_res)
        build_result = procgen.tileset_build(cfg_path, "res://tilesets/complete.tres")
        assert build_result.startswith("OK"), build_result

        audit_result = procgen.terrain_audit("res://tilesets/complete.tres")
        assert "CLEAN" in audit_result, audit_result
        assert "ERROR" not in audit_result.split("\n")[0], audit_result
        assert "| 0 | grass | MATCH_SIDES | 16 | 16 | 0 | 0 |" in audit_result, audit_result

    def test_incomplete_tileset_reports_exact_missing_gaps(self, tmp_project, tmp_path, monkeypatch):
        texture_res = self._make_fixture_atlas(tmp_project, monkeypatch)
        cfg_path = self._incomplete_config(tmp_path, texture_res)
        build_result = procgen.tileset_build(cfg_path, "res://tilesets/incomplete.tres")
        assert build_result.startswith("OK"), build_result

        audit_result = procgen.terrain_audit("res://tilesets/incomplete.tres")
        assert "| 0 | grass | MATCH_SIDES | 16 | 3 | 13 | 0 |" in audit_result, audit_result
        assert "missing signatures" in audit_result, audit_result

    def test_more_than_one_terrain_per_set_caught_on_real_tres(self, tmp_project, tmp_path, monkeypatch):
        """Build a clean tileset, then directly text-patch its saved `.tres`
        to add a second terrain to terrain_set_0 (a hand-edit / non-tileset_build
        origin scenario tileset_build's own validation cannot produce, since
        it rejects >1 terrain per set before ever launching Godot — but the
        audit must still catch it if it ever reaches a real .tres). Confirms
        the real audit catches the water-bottom law violation end to end.

        (The plan's other fixture requirement — a broken-ordering tile,
        terrain != -1 with terrain_set == -1 — is proven UNREACHABLE through
        any engine setter path: TileData.set_terrain() hard-refuses with
        `ERROR: Condition "terrain_set < 0 && p_terrain != -1"` when
        terrain_set is -1 (verified empirically on this machine's 4.6.2
        binary), so that fixture is exercised via a synthetic raw dump in the
        offline test_procgen_audit.py instead — it can only ever be reached by
        hand-editing the pseudo-properties across two DIFFERENT tiles, not by
        the engine's own load path.)"""
        texture_res = self._make_fixture_atlas(tmp_project, monkeypatch)
        cfg_path = self._complete_config(tmp_path, texture_res)
        build_result = procgen.tileset_build(cfg_path, "res://tilesets/two_terrain.tres")
        assert build_result.startswith("OK"), build_result

        tres_path = tmp_project / "tilesets" / "two_terrain.tres"
        text = tres_path.read_text(encoding="utf-8")
        marker = 'terrain_set_0/terrain_0/color = Color(0.29803923, 0.56078434, 0.23529412, 1)\n'
        assert marker in text, text
        text = text.replace(
            marker,
            marker + 'terrain_set_0/terrain_1/name = "sand"\nterrain_set_0/terrain_1/color = Color(0.8, 0.7, 0.4, 1)\n',
            1,
        )
        tres_path.write_text(text, encoding="utf-8")

        audit_result = procgen.terrain_audit("res://tilesets/two_terrain.tres")
        assert "ERRORS" in audit_result, audit_result
        assert "water-bottom law violation" in audit_result, audit_result

    def test_public_path_embeds_parseable_machine_coverage_json(self, tmp_project, tmp_path, monkeypatch):
        """procgen.terrain_audit's return string is the ONLY thing the
        in-house matcher (game repo) ever sees — it must carry both the
        markdown table AND a parseable machine `coverage` dict whose shape
        matches the docstring, not just the markdown."""
        texture_res = self._make_fixture_atlas(tmp_project, monkeypatch)
        cfg_path = self._complete_config(tmp_path, texture_res)
        build_result = procgen.tileset_build(cfg_path, "res://tilesets/coverage_json.tres")
        assert build_result.startswith("OK"), build_result

        audit_result = procgen.terrain_audit("res://tilesets/coverage_json.tres")
        assert "| 0 | grass | MATCH_SIDES | 16 | 16 | 0 | 0 |" in audit_result, audit_result
        assert "```json" in audit_result, audit_result

        fenced = audit_result.split("```json", 1)[1].split("```", 1)[0]
        coverage = json.loads(fenced)
        assert set(coverage.keys()) == {"0"}
        cov = coverage["0"]
        assert set(cov.keys()) == {
            "mode", "terrain_name", "expected_count", "covered_count", "missing", "variants", "signatures",
        }
        assert cov["mode"] == "MATCH_SIDES"
        assert cov["terrain_name"] == "grass"
        assert cov["expected_count"] == 16
        assert cov["covered_count"] == 16
        assert cov["missing"] == []

    def test_scoped_audit_still_catches_law_violation_in_a_different_set(self, tmp_project, tmp_path, monkeypatch):
        """The >1-terrain-per-set check is NOT scope-limited (docstring):
        build a tileset with two terrain sets, hand-patch a second terrain
        onto terrain_set 1 only, then audit scoped to terrain_set 0 — the
        violation living in the OTHER (unscoped) set must still be caught,
        while the coverage table/dict stays scoped to set 0 only."""
        texture_res = self._make_fixture_atlas(tmp_project, monkeypatch)
        cfg_path = self._two_terrain_set_config(tmp_path, texture_res)
        build_result = procgen.tileset_build(cfg_path, "res://tilesets/scoped_law.tres")
        assert build_result.startswith("OK"), build_result

        tres_path = tmp_project / "tilesets" / "scoped_law.tres"
        text = tres_path.read_text(encoding="utf-8")
        marker = 'terrain_set_1/terrain_0/color = Color(0.8784314, 0.7529412, 0.5019608, 1)\n'
        assert marker in text, text
        text = text.replace(
            marker,
            marker + 'terrain_set_1/terrain_1/name = "silt"\nterrain_set_1/terrain_1/color = Color(0.6, 0.5, 0.3, 1)\n',
            1,
        )
        tres_path.write_text(text, encoding="utf-8")

        audit_result = procgen.terrain_audit("res://tilesets/scoped_law.tres", terrain_set=0)
        assert "ERRORS" in audit_result, audit_result
        assert "water-bottom law violation" in audit_result, audit_result
        assert "terrain_set 1" in audit_result, audit_result

        # coverage table/dict itself stays scoped to the requested set only
        fenced = audit_result.split("```json", 1)[1].split("```", 1)[0]
        coverage = json.loads(fenced)
        assert set(coverage.keys()) == {"0"}


# A SYNTHETIC atlas laid out in the exact Minifantasy 3x5 edge-block arrangement
# (authored via Godot's Image — NO commercial art in the repo). 3 cols x 5 rows
# of 8x8 opaque cells = 24x40 px. Each cell's paint color is arbitrary; the audit
# reads the terrain PEERING BITS the minifantasy_edges strategy assigns, not the
# pixels, so a flat-color grid is sufficient to prove the strategy's cell->
# signature coverage end to end through a real headless build + audit.
_MAKE_MINIFANTASY_FIXTURE = r"""extends SceneTree
func _initialize() -> void:
	var w := 24
	var h := 40
	var img := Image.create(w, h, false, Image.FORMAT_RGBA8)
	img.fill(Color(0, 0, 0, 0))
	for gy in range(5):
		for gx in range(3):
			# alternate two tints so the grid is visibly a 3x5 block if ever inspected
			var c := Color(0.3, 0.6, 0.2, 1.0) if (gx + gy) % 2 == 0 else Color(0.25, 0.5, 0.18, 1.0)
			_fill_cell(img, gx, gy, c)
	var err := img.save_png(OS.get_environment("PROCGEN_FIXTURE_OUT"))
	print("FIXTURE_SAVE_RC=" + str(err))
	quit(0)

func _fill_cell(img: Image, gx: int, gy: int, col: Color) -> void:
	for py in range(8):
		for px in range(8):
			img.set_pixel(gx * 8 + px, gy * 8 + py, col)
"""


@pytest.mark.skipif(not _godot_available, reason="Godot binary not resolvable on this machine")
class TestMinifantasyEdgesStrategyGolden:
    """Committed, fully-offline-reproducible coverage for the parameterized
    `minifantasy_edges` strategy: build a SYNTHETIC 3x5 block through the real
    headless `procgen_tileset_build` with strategy='minifantasy_edges', then run
    the real `procgen_terrain_audit` and assert the exact MATCH_CORNERS coverage
    the empirically-read block yields — 15 of 16 classes covered, the lone
    missing class being the full-interior (all 4 corners land) tile a pond-ring
    block never depicts. A permutation error in the cell->signature order would
    still audit as clean (any 15 distinct classes), so the OFFLINE
    TestMinifantasyEdgesTable locks the per-cell reading; THIS live test locks
    that the strategy survives a real build+audit round-trip at a real origin."""

    @pytest.fixture()
    def tmp_project(self, tmp_path_factory, monkeypatch):
        proj = tmp_path_factory.mktemp("procgen_mf_proj")
        (proj / "project.godot").write_text(
            'config_version=5\n\n[application]\nconfig/name="ProcgenMinifantasyFixture"\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(config, "PROJECT_ROOT", proj)
        return proj

    def _make_fixture_atlas(self, proj: Path, monkeypatch) -> str:
        art = proj / "art"
        art.mkdir(parents=True, exist_ok=True)
        out_png = art / "mf_block.png"
        monkeypatch.setenv("PROCGEN_FIXTURE_OUT", str(out_png))
        r = runner.run_temp_probe(_MAKE_MINIFANTASY_FIXTURE, timeout=60)
        assert r.get("rc") == 0, f"fixture generation failed: {r}"
        assert out_png.exists(), f"fixture PNG not written: {r.get('out')}"
        return "res://art/mf_block.png"

    def _config(self, tmp_path: Path, texture_res: str) -> str:
        """strategy='minifantasy_edges' on the synthetic 3x5 block. The fixture
        atlas is exactly 3 cells wide, so the block sits at origin [0,0] here;
        the origin-translation itself (real sheets sit at cols 25/20/...) is
        covered offline in TestMinifantasyEdgesTable's origin test."""
        cfg = f"""
[tileset]
tile_size = [8, 8]

[[atlas]]
id = "ground"
texture = "{texture_res}"
scan = "all"

[[terrain_set]]
mode = "match_corners"
terrains = [ {{ name = "grass", color = "#4c8f3c" }} ]

[[terrain_assign]]
atlas = "ground"
strategy = "minifantasy_edges"
terrain = "grass"
origin = [0, 0]
"""
        p = tmp_path / "minifantasy.toml"
        p.write_text(cfg, encoding="utf-8")
        return str(p)

    def test_synthetic_block_builds_and_audits_15_of_16(self, tmp_project, tmp_path, monkeypatch):
        texture_res = self._make_fixture_atlas(tmp_project, monkeypatch)
        cfg_path = self._config(tmp_path, texture_res)
        build_result = procgen.tileset_build(cfg_path, "res://tilesets/minifantasy.tres")
        assert build_result.startswith("OK"), build_result
        # 15 block cells all get terrain bits (14 carry >=1 bit; the water-center
        # cell carries 0 bits but is still a created tile with terrain assigned).
        assert "tiles: 15" in build_result, build_result

        audit_result = procgen.terrain_audit("res://tilesets/minifantasy.tres")
        # 15 of the 16 MATCH_CORNERS classes covered, exactly 1 missing (the
        # full-interior all-4-corners tile the pond-ring block omits), no dupes.
        assert "| 0 | grass | MATCH_CORNERS | 16 | 15 | 1 | 0 |" in audit_result, audit_result

        fenced = audit_result.split("```json", 1)[1].split("```", 1)[0]
        coverage = json.loads(fenced)
        cov = coverage["0"]
        assert cov["mode"] == "MATCH_CORNERS"
        assert cov["expected_count"] == 16
        assert cov["covered_count"] == 15
        # the single missing class is precisely the all-4-corners interior
        assert cov["missing"] == [
            "BOTTOM_LEFT_CORNER,BOTTOM_RIGHT_CORNER,TOP_LEFT_CORNER,TOP_RIGHT_CORNER"
        ], cov["missing"]
        assert cov["variants"] == {}  # no signature carries >1 tile

        # spot-check two load-bearing per-cell signatures survived the round-trip
        # against the empirically-read block: the TL,BR diagonal at block (2,3)
        # and the water-center (no bits) at block (1,1).
        sigs = cov["signatures"]
        diag = sigs["BOTTOM_RIGHT_CORNER,TOP_LEFT_CORNER"]
        assert [t["coords"] for t in diag] == [[2, 3]], diag
        center = sigs[""]
        assert [t["coords"] for t in center] == [[1, 1]], center
