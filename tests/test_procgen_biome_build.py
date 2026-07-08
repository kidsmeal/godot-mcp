"""Golden build test for the v3 transparent-outside transition block
(Phase 1 of biome-world.plan.md).

Binary-gated: skipped when no Godot binary resolves, same guard as
test_procgen_build.py. Synthesizes TWO tiny synthetic fixture atlases via
Godot's Image: one 3x5 minifantasy_edges block whose "outside" pixels are
OPAQUE BLUE (the v2 land/water coastline block), and one whose "outside"
pixels are TRANSPARENT (the v3 land-land transition panel, lower biome shows
through). Both blocks share the identical LAND footprint (`_MINIFANTASY_EDGES_
LAND_CORNERS`). Builds each through a biome-set config and asserts the two
`.tres` outputs report IDENTICAL land bits and terrain-set counts — the
empirical proof that a transparent-outside block builds identically to an
opaque-outside block for the builder's land-tile handling, with NO builder
code change (the plan's §3.1 question, answered NO). One expected delta: the
opaque block's blue water-center (1,1) cell scans as a tile while the
transparent block's alpha-0 center is skipped, so tile/reload counts differ by
exactly that one cell (15 vs 14) — the intended v3 behavior, since the
transparent center is the biome-below hole and must not materialize."""
from __future__ import annotations

from pathlib import Path

import pytest

from godot_mcp import config, procgen, runner

_godot_available = bool(config.resolve_godot() and Path(config.resolve_godot()[0]).exists())

# The 3x5 minifantasy_edges block's LAND diagonal-corner footprint, one fixture
# script paints it as OPAQUE BLUE "outside" (v2 coastline), the other as
# TRANSPARENT "outside" (v3 transition panel). Every LAND corner pixel is the
# same opaque green in both, so the alpha-scan claim is isolated to the
# "outside" pixels alone.
_MAKE_FIXTURE_TEMPLATE = r"""extends SceneTree
func _initialize() -> void:
	var w := 24
	var h := 40
	var img := Image.create(w, h, false, Image.FORMAT_RGBA8)
	var outside := Color({outside_rgba})
	img.fill(outside)
	# minifantasy_edges 3x5 block at origin (0,0), 8x8 tiles.
	# Land corners painted opaque green; corners not in the block's land set
	# stay `outside`. Every cell gets at least one land-corner triangle stamp
	# so alpha > 0 for the whole cell footprint (the scan tests cell alpha,
	# not per-pixel shape), matching how the real art always has SOME opaque
	# land pixel in every one of the 15 cells (even the water-center (1,1),
	# which is deliberately ALL "outside" - no land pixel there at all).
	var land_cells := [
		Vector2i(0,0), Vector2i(1,0), Vector2i(2,0),
		Vector2i(0,1),               Vector2i(2,1),
		Vector2i(0,2), Vector2i(1,2), Vector2i(2,2),
		Vector2i(0,3), Vector2i(1,3), Vector2i(2,3),
		Vector2i(0,4), Vector2i(1,4), Vector2i(2,4),
	]
	for c in land_cells:
		_fill_cell(img, c.x, c.y, Color(0.3, 0.6, 0.2, 1.0))
	var err := img.save_png(OS.get_environment("PROCGEN_FIXTURE_OUT"))
	print("FIXTURE_SAVE_RC=" + str(err))
	quit(0)

func _fill_cell(img: Image, gx: int, gy: int, col: Color) -> void:
	for py in range(8):
		for px in range(8):
			img.set_pixel(gx * 8 + px, gy * 8 + py, col)
"""


@pytest.mark.skipif(not _godot_available, reason="Godot binary not resolvable on this machine")
class TestTransparentTransitionBuildsIdenticallyToOpaqueCoastline:
    @pytest.fixture()
    def tmp_project(self, tmp_path_factory, monkeypatch):
        proj = tmp_path_factory.mktemp("procgen_biome_proj")
        (proj / "project.godot").write_text(
            'config_version=5\n\n[application]\nconfig/name="ProcgenBiomeFixture"\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(config, "PROJECT_ROOT", proj)
        return proj

    def _make_fixture_atlas(self, proj: Path, monkeypatch, filename: str, outside_rgba: str) -> str:
        art = proj / "art"
        art.mkdir(parents=True, exist_ok=True)
        out_png = art / filename
        monkeypatch.setenv("PROCGEN_FIXTURE_OUT", str(out_png))
        source = _MAKE_FIXTURE_TEMPLATE.format(outside_rgba=outside_rgba)
        r = runner.run_temp_probe(source, timeout=60)
        assert r.get("rc") == 0, f"fixture generation failed: {r}"
        assert out_png.exists(), f"fixture PNG not written: {r.get('out')}"
        return f"res://art/{filename}"

    def _biome_set_config(self, texture_res: str) -> dict:
        return {
            "tileset": {"tile_size": [8, 8]},
            "atlas": [{"id": "ground", "texture": texture_res, "scan": "non_transparent"}],
            "biome_priority": ["plains"],
            "biome": [
                {
                    "name": "plains",
                    "atlas": "ground",
                    "panel": {"origin": [0, 0]},
                    "coastline": {"origin": [0, 0]},
                }
            ],
        }

    def _build_and_dump(self, tmp_project, tmp_path, monkeypatch, filename, outside_rgba, out_tres):
        texture_res = self._make_fixture_atlas(tmp_project, monkeypatch, filename, outside_rgba)
        cfg = procgen.validate_config(self._biome_set_config(texture_res))
        # Only one of the two role terrain_assign blocks is exercised per
        # fixture PNG (both share origin (0,0), the fixture paints ONE 3x5
        # block) — the assertion is that the REPORT is identical regardless of
        # whether "outside" was opaque blue or transparent, which is the
        # empirical proof the plan's Phase 1 asks for. Post-Phase-2-fix, the
        # roster expands to TWO terrain sets (`plains_panel`, `plains_coast`);
        # slicing BOTH the terrain_set list and the terrain_assign list down
        # to the first (panel) role isolates exactly one block, same as the
        # original single-terrain-set shape did.
        cfg["terrain_assign"] = cfg["terrain_assign"][:1]
        cfg["terrain_set"] = cfg["terrain_set"][:1]

        import godot_mcp.runner as runner_mod

        nonce = "biomebuild"
        src = procgen.compose_build_script(cfg, out_tres, nonce)
        r = runner_mod.run_temp_probe(src, timeout=120)
        out = r.get("out") or ""
        payload, reason = procgen.parse_sentinel_json(out, nonce)
        assert payload is not None, f"no sentinel payload: {reason}\n{out}"
        return payload

    def test_transparent_outside_and_opaque_outside_report_identically(self, tmp_project, tmp_path, monkeypatch):
        opaque_report = self._build_and_dump(
            tmp_project, tmp_path, monkeypatch, "coastline.png", "0.25, 0.44, 0.82, 1.0", "res://tilesets/coastline.tres"
        )
        transparent_report = self._build_and_dump(
            tmp_project, tmp_path, monkeypatch, "panel.png", "0, 0, 0, 0", "res://tilesets/panel.tres"
        )

        assert opaque_report.get("ok") is True, opaque_report
        assert transparent_report.get("ok") is True, transparent_report

        # Same bits assigned, same terrain sets — the LAND signature the
        # builder derives from cell alpha is identical regardless of what the
        # "outside" pixels are; only the water-center cell's fate differs
        # (see below), which is the expected, isolated delta.
        for key in ("total_bits_assigned", "terrain_sets"):
            assert opaque_report[key] == transparent_report[key], (
                f"{key} differs: opaque={opaque_report[key]!r} transparent={transparent_report[key]!r}"
            )
        # The water-center cell (1,1) carries NO land pixel in either fixture.
        # Under an OPAQUE-outside block (v2 coastline) its background is solid
        # blue (alpha=1.0), so the non_transparent scan creates it as a real
        # (unassigned-bits) water tile: 15 tiles, 0 skipped. Under a
        # TRANSPARENT-outside block (v3 panel) that same cell has alpha=0
        # everywhere, so the scan skips it: 14 tiles, 1 skipped. This is the
        # ONLY delta the transparent/opaque choice produces — every LAND cell
        # (all 14 corner-bearing cells) is created identically in both, which
        # is the empirical proof that transparent-outside == opaque-outside
        # for the builder's land-tile handling (the §3.1 question, answered NO).
        assert opaque_report["total_tiles"] == 15, opaque_report
        assert opaque_report["skipped_transparent"] == 0, opaque_report
        assert transparent_report["total_tiles"] == 14, transparent_report
        assert transparent_report["skipped_transparent"] == 1, transparent_report
        # reload count matches each build's own tile count (both reload cleanly)
        assert opaque_report["reload_tile_count"] == 15, opaque_report
        assert transparent_report["reload_tile_count"] == 14, transparent_report

    def test_transparent_outside_tres_reloads_with_expected_corner_wang_bits(self, tmp_project, tmp_path, monkeypatch):
        """The exit criterion's other half: the built .tres is loadable and its
        transition-panel tiles carry the expected corner-Wang bits (the
        minifantasy_edges land-corner signature at each cell). Exercises the
        real public `tileset_build` entry point end to end (config PATH ->
        .tres on disk), not just `compose_build_script` in isolation."""
        texture_res = self._make_fixture_atlas(tmp_project, monkeypatch, "panel2.png", "0, 0, 0, 0")

        import json

        cfg_path = tmp_path / "panel2.json"
        cfg_path.write_text(json.dumps(self._biome_set_config(texture_res)), encoding="utf-8")
        result = procgen.tileset_build(str(cfg_path), "res://tilesets/panel2.tres")
        assert result.startswith("OK"), result

        dump = r"""extends SceneTree
func _initialize() -> void:
	var ts := ResourceLoader.load("res://tilesets/panel2.tres", "TileSet", ResourceLoader.CACHE_MODE_IGNORE) as TileSet
	var src := ts.get_source(ts.get_source_id(0)) as TileSetAtlasSource
	# cell (1,0) block-relative -> land corners TOP_LEFT_CORNER, TOP_RIGHT_CORNER
	var td := src.get_tile_data(Vector2i(1, 0), 0)
	print("TL=" + str(td.get_terrain_peering_bit(TileSet.CELL_NEIGHBOR_TOP_LEFT_CORNER)))
	print("TR=" + str(td.get_terrain_peering_bit(TileSet.CELL_NEIGHBOR_TOP_RIGHT_CORNER)))
	print("BL=" + str(td.get_terrain_peering_bit(TileSet.CELL_NEIGHBOR_BOTTOM_LEFT_CORNER)))
	print("BR=" + str(td.get_terrain_peering_bit(TileSet.CELL_NEIGHBOR_BOTTOM_RIGHT_CORNER)))
	print("HAS_WATER_CENTER=" + str(src.has_tile(Vector2i(1, 1))))
	quit(0)
"""
        r = runner.run_temp_probe(dump, timeout=60)
        out = r.get("out") or ""
        assert "TL=0" in out and "TR=0" in out, out  # set to terrain 0
        assert "BL=-1" in out and "BR=-1" in out, out  # unset bits stay -1
        # the water-center cell has no land pixel anywhere -> never created
        assert "HAS_WATER_CENTER=false" in out, out


# --- Phase 2: two-biome multi-biome build + B1 audit-clean confirm --------
#
# ONE atlas, FOUR non-overlapping 3x5 minifantasy_edges blocks laid out left
# to right (each 3 cols x 5 rows): desert-panel(origin 0), desert-coastline
# (origin 3, opaque "outside"), swamp-panel(origin 6), swamp-coastline
# (origin 9, opaque "outside"). Land cells (the same `_MINIFANTASY_EDGES_
# LAND_CORNERS` footprint every block shares) are painted opaque green in ALL
# FOUR blocks; only the two coastline blocks additionally paint their
# "outside" cells opaque blue (the panel blocks' outside stays transparent —
# global fill).
_MAKE_TWO_BIOME_FIXTURE = r"""extends SceneTree
func _initialize() -> void:
	var w := 96
	var h := 40
	var img := Image.create(w, h, false, Image.FORMAT_RGBA8)
	img.fill(Color(0, 0, 0, 0))
	var land_cells := [
		Vector2i(0,0), Vector2i(1,0), Vector2i(2,0),
		Vector2i(0,1),               Vector2i(2,1),
		Vector2i(0,2), Vector2i(1,2), Vector2i(2,2),
		Vector2i(0,3), Vector2i(1,3), Vector2i(2,3),
		Vector2i(0,4), Vector2i(1,4), Vector2i(2,4),
	]
	var coastline_origins := [3, 9]
	var outside_col := Color(0.25, 0.44, 0.82, 1.0)
	for ox in coastline_origins:
		for gy in range(5):
			for gx in range(3):
				_fill_cell(img, ox + gx, gy, outside_col)
	var all_origins := [0, 3, 6, 9]
	for ox in all_origins:
		for c in land_cells:
			_fill_cell(img, ox + c.x, c.y, Color(0.3, 0.6, 0.2, 1.0))
	var err := img.save_png(OS.get_environment("PROCGEN_FIXTURE_OUT"))
	print("FIXTURE_SAVE_RC=" + str(err))
	quit(0)

func _fill_cell(img: Image, gx: int, gy: int, col: Color) -> void:
	for py in range(8):
		for px in range(8):
			img.set_pixel(gx * 8 + px, gy * 8 + py, col)
"""


# One "lake" biome: panel at origin 0 (transparent outside), coastline at
# origin 3 (opaque water outside) whose water-center cell — block-relative
# (1,1), absolute (4,1) — is the animated water tile (§3.2). Frame 1 is
# reserved 3 cols to the right at (7,1), well clear of both 3x5 blocks
# (cols 0-2 and 3-5), so the canvas only needs to be wide enough to hold that
# reserved region's pixels (it needs no paint of its own — reserved cells are
# never scanned).
_MAKE_ANIMATED_WATER_FIXTURE = r"""extends SceneTree
func _initialize() -> void:
	var w := 72
	var h := 40
	var img := Image.create(w, h, false, Image.FORMAT_RGBA8)
	img.fill(Color(0, 0, 0, 0))
	var land_cells := [
		Vector2i(0,0), Vector2i(1,0), Vector2i(2,0),
		Vector2i(0,1),               Vector2i(2,1),
		Vector2i(0,2), Vector2i(1,2), Vector2i(2,2),
		Vector2i(0,3), Vector2i(1,3), Vector2i(2,3),
		Vector2i(0,4), Vector2i(1,4), Vector2i(2,4),
	]
	var outside_col := Color(0.25, 0.44, 0.82, 1.0)
	for gy in range(5):
		for gx in range(3):
			_fill_cell(img, 3 + gx, gy, outside_col)
	for ox in [0, 3]:
		for c in land_cells:
			_fill_cell(img, ox + c.x, c.y, Color(0.3, 0.6, 0.2, 1.0))
	var err := img.save_png(OS.get_environment("PROCGEN_FIXTURE_OUT"))
	print("FIXTURE_SAVE_RC=" + str(err))
	quit(0)

func _fill_cell(img: Image, gx: int, gy: int, col: Color) -> void:
	for py in range(8):
		for px in range(8):
			img.set_pixel(gx * 8 + px, gy * 8 + py, col)
"""


@pytest.mark.skipif(not _godot_available, reason="Godot binary not resolvable on this machine")
class TestTwoBiomeMultiBiomeBuildAndAudit:
    """Phase 2 of biome-world.plan.md: ONE biome-set config with priority
    `desert > swamp` builds a multi-biome tileset carrying BOTH biomes' panel
    + coastline tiles in one `.tres`, and `procgen_terrain_audit` reports it
    CLEAN per ROLE terrain set independently (`desert_panel`, `desert_coast`,
    `swamp_panel`, `swamp_coast`) — the B1 cross-repo confirm (the emitted
    corner-Wang bits are the exact signatures the game's flipped "is biome Y"
    matcher will read) AND the FIX (2026-07-08 amendment) proof that a
    missing class in one role's coverage can no longer be masked by the
    other role's tile sharing that signature, since panel and coastline are
    no longer the same terrain."""

    @pytest.fixture()
    def tmp_project(self, tmp_path_factory, monkeypatch):
        proj = tmp_path_factory.mktemp("procgen_biome2_proj")
        (proj / "project.godot").write_text(
            'config_version=5\n\n[application]\nconfig/name="ProcgenBiome2Fixture"\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(config, "PROJECT_ROOT", proj)
        return proj

    def _make_two_biome_fixture_atlas(self, proj: Path, monkeypatch) -> str:
        art = proj / "art"
        art.mkdir(parents=True, exist_ok=True)
        out_png = art / "two_biome.png"
        monkeypatch.setenv("PROCGEN_FIXTURE_OUT", str(out_png))
        r = runner.run_temp_probe(_MAKE_TWO_BIOME_FIXTURE, timeout=60)
        assert r.get("rc") == 0, f"fixture generation failed: {r}"
        assert out_png.exists(), f"fixture PNG not written: {r.get('out')}"
        return "res://art/two_biome.png"

    def _two_biome_config(self, texture_res: str) -> dict:
        return {
            "tileset": {"tile_size": [8, 8]},
            "atlas": [{"id": "ground", "texture": texture_res, "scan": "non_transparent"}],
            "biome_priority": ["desert", "swamp"],
            "biome": [
                {"name": "desert", "atlas": "ground", "panel": {"origin": [0, 0]}, "coastline": {"origin": [3, 0]}},
                {"name": "swamp", "atlas": "ground", "panel": {"origin": [6, 0]}, "coastline": {"origin": [9, 0]}},
            ],
        }

    def test_two_biome_tileset_builds_both_biomes_and_audits_clean(self, tmp_project, tmp_path, monkeypatch):
        import json

        texture_res = self._make_two_biome_fixture_atlas(tmp_project, monkeypatch)
        normalized = procgen.validate_config(self._two_biome_config(texture_res))
        # priority order is deterministic in the normalized output actually
        # driving this build (not just re-derived in an offline test).
        assert normalized["biome_priority"] == ["desert", "swamp"]

        cfg_path = tmp_path / "two_biome.json"
        cfg_path.write_text(json.dumps(self._two_biome_config(texture_res)), encoding="utf-8")

        build_result = procgen.tileset_build(str(cfg_path), "res://tilesets/two_biome.tres")
        assert build_result.startswith("OK"), build_result
        # 2 biomes x (14 panel land cells + 15 coastline cells incl. its
        # opaque water-center) = 58 tiles carrying both biomes' panel AND
        # coastline tiles.
        assert "tiles: 58" in build_result, build_result
        # 2 biomes x 2 roles = 4 single-terrain terrain sets (the fix: panel
        # and coastline are no longer merged under one shared terrain).
        assert "terrain sets: 4" in build_result, build_result
        # each biome's panel water-center cell (transparent, alpha=0) is the
        # one expected skip per biome
        assert "skipped transparent: 2" in build_result, build_result
        # reload count matches the built tile count
        assert "reload check: 58 tiles" in build_result, build_result

        audit_result = procgen.terrain_audit("res://tilesets/two_biome.tres")
        assert "CLEAN" in audit_result, audit_result
        assert "ERRORS" not in audit_result, audit_result
        # Each ROLE terrain set is now independently audited — no cross-role
        # masking. A panel block (transparent outside) never materializes its
        # water-center cell, so it covers only the 14 land-corner classes
        # (missing both the empty/no-neighbor class AND the full-interior
        # class: 2 missing of 16). A coastline block (opaque outside)
        # materializes all 15 cells, covering 15/16 (missing only the
        # full-interior class). Neither role has ANY variants — with roles
        # split, no signature is ever covered by more than one tile, which is
        # exactly the defect this fix closes (the old shared-terrain shape
        # reported 14 variants per biome here).
        assert "| 0 | desert_panel | MATCH_CORNERS | 16 | 14 | 2 | 0 |" in audit_result, audit_result
        assert "| 1 | desert_coast | MATCH_CORNERS | 16 | 15 | 1 | 0 |" in audit_result, audit_result
        assert "| 2 | swamp_panel | MATCH_CORNERS | 16 | 14 | 2 | 0 |" in audit_result, audit_result
        assert "| 3 | swamp_coast | MATCH_CORNERS | 16 | 15 | 1 | 0 |" in audit_result, audit_result

        fenced = audit_result.split("```json", 1)[1].split("```", 1)[0]
        coverage = json.loads(fenced)
        assert set(coverage.keys()) == {"0", "1", "2", "3"}
        assert coverage["0"]["terrain_name"] == "desert_panel"
        assert coverage["1"]["terrain_name"] == "desert_coast"
        assert coverage["2"]["terrain_name"] == "swamp_panel"
        assert coverage["3"]["terrain_name"] == "swamp_coast"
        # a missing class in EITHER role's own coverage list is never emptied
        # out by the other role's tile — each role's `missing` list stands on
        # its own (the audit's masking-proof: querying one role never reads
        # the other's coverage).
        assert coverage["0"]["missing"] and coverage["2"]["missing"]  # panels: 2 missing classes each
        assert coverage["1"]["missing"] and coverage["3"]["missing"]  # coastlines: 1 missing class each
        assert coverage["0"]["variants"] == {}
        assert coverage["1"]["variants"] == {}
        assert coverage["2"]["variants"] == {}
        assert coverage["3"]["variants"] == {}

    def _make_animated_water_fixture_atlas(self, proj: Path, monkeypatch) -> str:
        art = proj / "art"
        art.mkdir(parents=True, exist_ok=True)
        out_png = art / "lake.png"
        monkeypatch.setenv("PROCGEN_FIXTURE_OUT", str(out_png))
        r = runner.run_temp_probe(_MAKE_ANIMATED_WATER_FIXTURE, timeout=60)
        assert r.get("rc") == 0, f"fixture generation failed: {r}"
        assert out_png.exists(), f"fixture PNG not written: {r.get('out')}"
        return "res://art/lake.png"

    def _animated_water_biome_config(self, texture_res: str) -> dict:
        return {
            "tileset": {"tile_size": [8, 8]},
            "atlas": [{"id": "ground", "texture": texture_res, "scan": "non_transparent"}],
            "biome_priority": ["lake"],
            "biome": [
                {"name": "lake", "atlas": "ground", "panel": {"origin": [0, 0]}, "coastline": {"origin": [3, 0]}},
            ],
            "animation": [
                {
                    "atlas": "ground",
                    "base_region": [[4, 1], [4, 1]],
                    "frames": 2,
                    "frame_offset": [3, 0],
                    "duration": 0.5,
                    "mode": "default",
                }
            ],
        }

    def test_animated_water_biome_is_pure_config_and_audits_clean_for_animation_sync(
        self, tmp_project, tmp_path, monkeypatch
    ):
        """§3.2 confirm: an animated water/lake biome is expressed ENTIRELY
        as an `[[animation]]` config group (mode='default', per the existing
        water-bearing-tile rule `validate_config` already enforces) on the
        biome's coastline water-center cell — NO new tool code. The built
        `.tres` reloads with the animation intact AND the audit's existing
        animation-sync lint reports clean."""
        import json

        texture_res = self._make_animated_water_fixture_atlas(tmp_project, monkeypatch)
        cfg_path = tmp_path / "lake.json"
        cfg_path.write_text(json.dumps(self._animated_water_biome_config(texture_res)), encoding="utf-8")

        build_result = procgen.tileset_build(str(cfg_path), "res://tilesets/lake.tres")
        assert build_result.startswith("OK"), build_result
        assert "animated groups: 1" in build_result, build_result
        assert "1 reserved frame regions" in build_result, build_result

        # real-input reload check: the animation itself survived serialization,
        # on the exact cell the coastline's minifantasy_edges block assigned
        # a terrain to (the water-center), not just a report-string claim.
        dump = r"""extends SceneTree
func _initialize() -> void:
	var ts := ResourceLoader.load("res://tilesets/lake.tres", "TileSet", ResourceLoader.CACHE_MODE_IGNORE) as TileSet
	var src := ts.get_source(ts.get_source_id(0)) as TileSetAtlasSource
	var td := src.get_tile_data(Vector2i(4, 1), 0)
	print("FRAMES=" + str(src.get_tile_animation_frames_count(Vector2i(4, 1))))
	print("MODE=" + str(src.get_tile_animation_mode(Vector2i(4, 1))))
	print("TERRAIN=" + str(td.terrain))
	quit(0)
"""
        r = runner.run_temp_probe(dump, timeout=60)
        out = r.get("out") or ""
        assert "FRAMES=2" in out, out
        assert "MODE=0" in out, out  # TILE_ANIMATION_MODE_DEFAULT
        assert "TERRAIN=0" in out, out  # the lake terrain, not unassigned

        audit_result = procgen.terrain_audit("res://tilesets/lake.tres")
        assert "CLEAN" in audit_result, audit_result
        assert "ERRORS" not in audit_result, audit_result
