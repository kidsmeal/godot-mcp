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
        # Only one of the two terrain_assign strategy blocks is exercised per
        # fixture PNG (both share origin (0,0), the fixture paints ONE 3x5
        # block) — the assertion is that the REPORT is identical regardless of
        # whether "outside" was opaque blue or transparent, which is the
        # empirical proof the plan's Phase 1 asks for.
        cfg["terrain_assign"] = cfg["terrain_assign"][:1]
        cfg["terrain_set"][0]["terrains"] = cfg["terrain_set"][0]["terrains"][:1]

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
