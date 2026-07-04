"""Golden-file build test for procgen_tileset_build.

Binary-gated: skipped when no Godot binary resolves. Generates a tiny SYNTHETIC
fixture atlas programmatically (via Godot's Image — the repo has no PIL dep, and
the real commercial Minifantasy pack must never be copied in), writes a golden
config, runs the real headless build, and asserts the .tres reports the expected
tile count / terrains / animation groups / reserved frame regions AND reloads.

Fixture atlas layout (8x8 tiles, 4 cols x 2 rows = 32x16 px):
  row 0: cols 0-2 opaque (static tiles), col 3 transparent (skipped by scan)
  row 1: col 0 = animation BASE (frame 0), col 1 = its RESERVED frame 1,
         cols 2-3 transparent
So a non_transparent scan should create 3 static tiles + 1 animated base = 4
tiles, reserve 1 frame region, and skip the transparent cells.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from godot_mcp import config, procgen, runner

_godot_available = bool(config.resolve_godot() and Path(config.resolve_godot()[0]).exists())

# GDScript run headless to author the synthetic fixture PNG in-place. Kept tiny;
# it just paints a few opaque cells and one animation base + reserved frame.
_MAKE_FIXTURE = r"""extends SceneTree
func _initialize() -> void:
	var w := 32
	var h := 16
	var img := Image.create(w, h, false, Image.FORMAT_RGBA8)
	img.fill(Color(0, 0, 0, 0))
	# opaque static tiles at grid (0,0),(1,0),(2,0)
	_fill_cell(img, 0, 0, Color(0.3, 0.6, 0.2, 1.0))
	_fill_cell(img, 1, 0, Color(0.3, 0.6, 0.2, 1.0))
	_fill_cell(img, 2, 0, Color(0.3, 0.6, 0.2, 1.0))
	# animation base at (0,1) + its reserved frame 1 at (1,1)
	_fill_cell(img, 0, 1, Color(0.1, 0.3, 0.7, 1.0))
	_fill_cell(img, 1, 1, Color(0.1, 0.3, 0.8, 1.0))
	var err := img.save_png(OS.get_environment("PROCGEN_FIXTURE_OUT"))
	print("FIXTURE_SAVE_RC=" + str(err))
	quit(0)

func _fill_cell(img: Image, gx: int, gy: int, col: Color) -> void:
	for py in range(8):
		for px in range(8):
			img.set_pixel(gx * 8 + px, gy * 8 + py, col)
"""


@pytest.mark.skipif(not _godot_available, reason="Godot binary not resolvable on this machine")
class TestTilesetBuildGolden:
    @pytest.fixture()
    def tmp_project(self, tmp_path_factory, monkeypatch):
        proj = tmp_path_factory.mktemp("procgen_proj")
        (proj / "project.godot").write_text(
            'config_version=5\n\n[application]\nconfig/name="ProcgenFixture"\n',
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

    def _golden_config(self, tmp_path: Path, texture_res: str) -> str:
        cfg = f"""
[tileset]
tile_size = [8, 8]

[[atlas]]
id = "ground"
texture = "{texture_res}"
scan = "non_transparent"

[[animation]]
atlas = "ground"
base_region = [[0, 1], [0, 1]]
frames = 2
frame_offset = [1, 0]
duration = 0.6
mode = "default"

[[terrain_set]]
mode = "match_corners_and_sides"
terrains = [ {{ name = "grass", color = "#4c8f3c" }} ]

[[terrain_assign]]
atlas = "ground"
strategy = "explicit"
terrain = "grass"
tiles = [ {{ coords = [0, 0], bits = ["TOP_SIDE", "LEFT_SIDE"] }} ]

[physics]
default_full_square = ["grass"]

[custom_data]
layers = [ {{ name = "biome_id", type = "string" }} ]
"""
        p = tmp_path / "plains.toml"
        p.write_text(cfg, encoding="utf-8")
        return str(p)

    def test_build_reports_expected_and_reloads(self, tmp_project, tmp_path, monkeypatch):
        texture_res = self._make_fixture_atlas(tmp_project, monkeypatch)
        cfg_path = self._golden_config(tmp_path, texture_res)

        result = procgen.tileset_build(cfg_path, "res://tilesets/plains.tres")

        assert result.startswith("OK"), f"build did not succeed:\n{result}"
        # 3 static opaque + 1 animation base = 4 tiles created
        assert "tiles: 4" in result, result
        # 1 animated group, 1 reserved frame region
        assert "animated groups: 1" in result, result
        assert "1 reserved frame regions" in result, result
        # terrain set present + peering bits assigned (2 from the explicit tile)
        assert "terrain sets: 1" in result, result
        assert "peering bits: 2" in result, result
        # transparent cells skipped (col3 row0, cols2-3 row1 = 3 transparent)
        assert "skipped transparent: 3" in result, result
        # reload sanity check saw the tiles
        assert "reload check: 4 tiles" in result, result

        # the .tres actually landed on disk
        tres = tmp_project / "tilesets" / "plains.tres"
        assert tres.exists()

        # Reload the saved .tres in a fresh engine and confirm the terrain bits
        # AND the animation survived serialization (the real-input path end to
        # end, not just the in-build report).
        dump = r"""extends SceneTree
func _initialize() -> void:
	var ts := ResourceLoader.load("res://tilesets/plains.tres", "TileSet", ResourceLoader.CACHE_MODE_IGNORE) as TileSet
	var src := ts.get_source(ts.get_source_id(0)) as TileSetAtlasSource
	var td := src.get_tile_data(Vector2i(0, 0), 0)
	print("TS=" + str(td.terrain_set))
	print("TERR=" + str(td.terrain))
	print("TOP=" + str(td.get_terrain_peering_bit(TileSet.CELL_NEIGHBOR_TOP_SIDE)))
	print("LEFT=" + str(td.get_terrain_peering_bit(TileSet.CELL_NEIGHBOR_LEFT_SIDE)))
	print("RIGHT=" + str(td.get_terrain_peering_bit(TileSet.CELL_NEIGHBOR_RIGHT_SIDE)))
	print("FRAMES=" + str(src.get_tile_animation_frames_count(Vector2i(0, 1))))
	print("MODE=" + str(src.get_tile_animation_mode(Vector2i(0, 1))))
	quit(0)
"""
        r = runner.run_temp_probe(dump, timeout=60)
        out = r.get("out") or ""
        assert "TS=0" in out, out
        assert "TERR=0" in out, out
        assert "TOP=0" in out and "LEFT=0" in out, out  # bits set to terrain 0
        assert "RIGHT=-1" in out, out                    # unset bit is -1
        assert "FRAMES=2" in out, out                    # animation survived
        assert "MODE=0" in out, out                      # DEFAULT (synchronized)

    def test_more_than_one_terrain_rejected_before_launch(self, tmp_project, tmp_path):
        cfg = """
[tileset]
tile_size = [8, 8]
[[atlas]]
id = "ground"
texture = "res://art/fixture.png"
[[terrain_set]]
mode = "match_corners_and_sides"
terrains = [ { name = "grass" }, { name = "sand" } ]
"""
        p = tmp_path / "bad.toml"
        p.write_text(cfg, encoding="utf-8")
        result = procgen.tileset_build(str(p), "res://tilesets/bad.tres")
        assert result.startswith("ERROR")
        assert "ONE terrain" in result
