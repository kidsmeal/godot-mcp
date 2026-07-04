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

    def test_plain_config_creates_no_physics_or_nav_layer(self, tmp_project, tmp_path, monkeypatch):
        """P1-review carry-in: a config that declares neither collision nor
        navigation must not bake an unused physics/nav layer into the .tres."""
        texture_res = self._make_fixture_atlas(tmp_project, monkeypatch)
        cfg = f"""
[tileset]
tile_size = [8, 8]

[[atlas]]
id = "ground"
texture = "{texture_res}"
scan = "non_transparent"
"""
        p = tmp_path / "plain.toml"
        p.write_text(cfg, encoding="utf-8")
        result = procgen.tileset_build(str(p), "res://tilesets/plain.tres")
        assert result.startswith("OK"), result

        dump = r"""extends SceneTree
func _initialize() -> void:
	var ts := ResourceLoader.load("res://tilesets/plain.tres", "TileSet", ResourceLoader.CACHE_MODE_IGNORE) as TileSet
	print("PHYSICS_LAYERS=" + str(ts.get_physics_layers_count()))
	print("NAV_LAYERS=" + str(ts.get_navigation_layers_count()))
	quit(0)
"""
        r = runner.run_temp_probe(dump, timeout=60)
        out = r.get("out") or ""
        assert "PHYSICS_LAYERS=0" in out, out
        assert "NAV_LAYERS=0" in out, out

    def test_physics_declared_creates_exactly_one_physics_layer(self, tmp_project, tmp_path, monkeypatch):
        """The golden config declares [physics].default_full_square, so exactly
        one physics layer is created (and still no nav layer, since the config
        has no navigation section)."""
        texture_res = self._make_fixture_atlas(tmp_project, monkeypatch)
        cfg_path = self._golden_config(tmp_path, texture_res)
        result = procgen.tileset_build(cfg_path, "res://tilesets/plains2.tres")
        assert result.startswith("OK"), result

        dump = r"""extends SceneTree
func _initialize() -> void:
	var ts := ResourceLoader.load("res://tilesets/plains2.tres", "TileSet", ResourceLoader.CACHE_MODE_IGNORE) as TileSet
	print("PHYSICS_LAYERS=" + str(ts.get_physics_layers_count()))
	print("NAV_LAYERS=" + str(ts.get_navigation_layers_count()))
	quit(0)
"""
        r = runner.run_temp_probe(dump, timeout=60)
        out = r.get("out") or ""
        assert "PHYSICS_LAYERS=1" in out, out
        assert "NAV_LAYERS=0" in out, out

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

    def test_json_config_builds_equivalent_tileset_to_toml(self, tmp_project, tmp_path, monkeypatch):
        """P1-hardening finding #1: a .json config must build a tileset
        end to end, headless, with the same reported tile/terrain/animation
        counts as the equivalent .toml golden config."""
        import json

        texture_res = self._make_fixture_atlas(tmp_project, monkeypatch)
        json_cfg = {
            "tileset": {"tile_size": [8, 8]},
            "atlas": [{"id": "ground", "texture": texture_res, "scan": "non_transparent"}],
            "animation": [
                {
                    "atlas": "ground",
                    "base_region": [[0, 1], [0, 1]],
                    "frames": 2,
                    "frame_offset": [1, 0],
                    "duration": 0.6,
                    "mode": "default",
                }
            ],
            "terrain_set": [{"mode": "match_corners_and_sides", "terrains": [{"name": "grass", "color": "#4c8f3c"}]}],
            "terrain_assign": [
                {
                    "atlas": "ground",
                    "strategy": "explicit",
                    "terrain": "grass",
                    "tiles": [{"coords": [0, 0], "bits": ["TOP_SIDE", "LEFT_SIDE"]}],
                }
            ],
            "physics": {"default_full_square": ["grass"]},
            "custom_data": {"layers": [{"name": "biome_id", "type": "string"}]},
        }
        cfg_path = tmp_path / "plains.json"
        cfg_path.write_text(json.dumps(json_cfg), encoding="utf-8")

        result = procgen.tileset_build(str(cfg_path), "res://tilesets/plains_json.tres")
        assert result.startswith("OK"), f"build did not succeed:\n{result}"
        # Same expectations as the .toml golden-file build (test_build_reports_expected_and_reloads).
        assert "tiles: 4" in result, result
        assert "animated groups: 1" in result, result
        assert "1 reserved frame regions" in result, result
        assert "terrain sets: 1" in result, result
        assert "peering bits: 2" in result, result
        assert "skipped transparent: 3" in result, result
        assert "reload check: 4 tiles" in result, result

        tres = tmp_project / "tilesets" / "plains_json.tres"
        assert tres.exists()


@pytest.mark.skipif(not _godot_available, reason="Godot binary not resolvable on this machine")
class TestTilesetBuildSeparatedAtlas:
    """P1-hardening finding #3: a nonzero atlas `separation` must scan the
    correct number of grid cells. The naive (image - margin) / (tile +
    separation) formula drops the final tile/column whenever separation is
    nonzero; the fixed grid-count math adds one `separation` allowance before
    dividing.

    Fixture atlas layout: 3 cols x 2 rows of 8x8 opaque tiles, margin (0,0),
    separation (2,2) — sheet is 28x18px (3*8 + 2*2 = 28 wide, 2*8 + 1*2 = 18
    tall). Every cell is opaque so scan='all' vs 'non_transparent' both see
    the full 6-tile grid; the bug under test is the grid DIMENSION count, not
    the alpha test."""

    @pytest.fixture()
    def tmp_project(self, tmp_path_factory, monkeypatch):
        proj = tmp_path_factory.mktemp("procgen_sep_proj")
        (proj / "project.godot").write_text(
            'config_version=5\n\n[application]\nconfig/name="ProcgenSepFixture"\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(config, "PROJECT_ROOT", proj)
        return proj

    _MAKE_SEPARATED_FIXTURE = r"""extends SceneTree
func _initialize() -> void:
	var w := 28
	var h := 18
	var img := Image.create(w, h, false, Image.FORMAT_RGBA8)
	img.fill(Color(0, 0, 0, 0))
	for gy in range(2):
		for gx in range(3):
			_fill_cell(img, gx, gy, Color(0.3, 0.6, 0.2, 1.0))
	var err := img.save_png(OS.get_environment("PROCGEN_FIXTURE_OUT"))
	print("FIXTURE_SAVE_RC=" + str(err))
	quit(0)

func _fill_cell(img: Image, gx: int, gy: int, col: Color) -> void:
	var ox := gx * (8 + 2)
	var oy := gy * (8 + 2)
	for py in range(8):
		for px in range(8):
			img.set_pixel(ox + px, oy + py, col)
"""

    def _make_fixture_atlas(self, proj: Path, monkeypatch) -> str:
        art = proj / "art"
        art.mkdir(parents=True, exist_ok=True)
        out_png = art / "separated.png"
        monkeypatch.setenv("PROCGEN_FIXTURE_OUT", str(out_png))
        r = runner.run_temp_probe(self._MAKE_SEPARATED_FIXTURE, timeout=60)
        assert r.get("rc") == 0, f"fixture generation failed: {r}"
        assert out_png.exists(), f"fixture PNG not written: {r.get('out')}"
        return "res://art/separated.png"

    def test_nonzero_separation_scans_correct_tile_count(self, tmp_project, tmp_path, monkeypatch):
        texture_res = self._make_fixture_atlas(tmp_project, monkeypatch)
        cfg = f"""
[tileset]
tile_size = [8, 8]

[[atlas]]
id = "ground"
texture = "{texture_res}"
separation = [2, 2]
scan = "all"
"""
        p = tmp_path / "separated.toml"
        p.write_text(cfg, encoding="utf-8")
        result = procgen.tileset_build(str(p), "res://tilesets/separated.tres")
        assert result.startswith("OK"), f"build did not succeed:\n{result}"
        # 3 cols x 2 rows = 6 tiles. The pre-fix formula undercounts this to
        # 2 cols x 1 row = 2 tiles (drops the final column/row whenever
        # separation is nonzero).
        assert "tiles: 6" in result, result
        assert "reload check: 6 tiles" in result, result
