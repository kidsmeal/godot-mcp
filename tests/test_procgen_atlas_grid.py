"""Offline tests for procgen_atlas_grid (pure Pillow — no Godot binary needed).

Generates a small synthetic PNG in-test and asserts the rendered grid's
dimensions match the upscale + margin math, for both a full-sheet render and a
region crop. Also covers containment refusal, missing-file / malformed-region
error strings, and that the returned content actually carries image data (not
just a path) — the FastMCP `Image` helper the tool returns.
"""
from __future__ import annotations

import asyncio
import base64
from io import BytesIO
from pathlib import Path

import pytest
from mcp.types import ImageContent, TextContent
from PIL import Image as PILImage

from godot_mcp import config, procgen

_MARGIN = procgen._ATLAS_GRID_MARGIN


def _make_sheet(path: Path, cols: int, rows: int, tile: int = 8) -> None:
    """A synthetic tile-grid PNG: alternating opaque colors per tile so the
    checkerboard-for-transparency compositing has real content to composite
    over (not just a blank canvas)."""
    im = PILImage.new("RGBA", (cols * tile, rows * tile), (0, 0, 0, 0))
    for ty in range(rows):
        for tx in range(cols):
            color = (255, 0, 0, 255) if (tx + ty) % 2 == 0 else (0, 255, 0, 255)
            for py in range(tile):
                for px in range(tile):
                    im.putpixel((tx * tile + px, ty * tile + py), color)
    im.save(path)


@pytest.fixture()
def tmp_project(tmp_path_factory, monkeypatch):
    proj = tmp_path_factory.mktemp("atlas_grid_project")
    (proj / "project.godot").write_text(
        'config_version=5\n\n[application]\nconfig/name="AtlasGridFixture"\n', encoding="utf-8"
    )
    monkeypatch.setattr(config, "PROJECT_ROOT", proj)
    return proj


# ---------------------------------------------------------------------------
# region parsing
# ---------------------------------------------------------------------------


class TestParseRegion:
    def test_valid_region_parses(self):
        assert procgen.parse_region("25:32,3:8") == (25, 32, 3, 8)

    def test_missing_comma_is_an_error(self):
        with pytest.raises(procgen.AtlasGridError):
            procgen.parse_region("25:32 3:8")

    def test_missing_colon_is_an_error(self):
        with pytest.raises(procgen.AtlasGridError):
            procgen.parse_region("2532,38")

    def test_non_integer_bounds_is_an_error(self):
        with pytest.raises(procgen.AtlasGridError):
            procgen.parse_region("a:b,3:8")

    def test_inverted_bounds_is_an_error(self):
        with pytest.raises(procgen.AtlasGridError):
            procgen.parse_region("10:5,3:8")

    def test_equal_bounds_is_an_error(self):
        with pytest.raises(procgen.AtlasGridError):
            procgen.parse_region("5:5,3:8")

    def test_negative_bound_is_an_error(self):
        with pytest.raises(procgen.AtlasGridError):
            procgen.parse_region("-1:5,3:8")


# ---------------------------------------------------------------------------
# rendering dimensions
# ---------------------------------------------------------------------------


class TestAtlasGridFullSheet:
    def test_full_sheet_dimensions_match_upscale_plus_margin(self, tmp_project):
        cols, rows, tile, scale = 8, 4, 8, 6
        sheet = tmp_project / "sheet.png"
        _make_sheet(sheet, cols, rows, tile)

        result = procgen.atlas_grid("res://sheet.png", tile_size=tile, scale=scale)
        assert isinstance(result, list)
        summary, image = result
        assert isinstance(summary, str)
        assert f"{cols}x{rows}" in summary

        expected_w = cols * tile * scale + _MARGIN
        expected_h = rows * tile * scale + _MARGIN
        # decode the returned image bytes back to confirm real pixel dims
        content = image.to_image_content()
        raw = base64.b64decode(content.data)
        decoded = PILImage.open(BytesIO(raw))
        assert decoded.size == (expected_w, expected_h)

    def test_default_tile_size_and_scale(self, tmp_project):
        """tile_size=8 (game default), scale=6 (default) -> 48px per tile."""
        sheet = tmp_project / "sheet.png"
        _make_sheet(sheet, 4, 4, tile=8)
        result = procgen.atlas_grid("res://sheet.png")
        assert isinstance(result, list)
        summary = result[0]
        assert "scale: 6x" in summary
        assert "tile_size=8" in summary


class TestAtlasGridRegionCrop:
    def test_region_crop_dimensions_match_upscale_plus_margin(self, tmp_project):
        tile, scale = 8, 6
        sheet = tmp_project / "sheet.png"
        _make_sheet(sheet, 40, 20, tile)

        region = "25:32,3:8"  # cols 25-31 (7 cols), rows 3-7 (5 rows)
        result = procgen.atlas_grid("res://sheet.png", tile_size=tile, scale=scale, region=region)
        assert isinstance(result, list)
        summary, image = result
        assert "cols 25-31, rows 3-7" in summary
        assert "7x5" in summary

        expected_w = 7 * tile * scale + _MARGIN
        expected_h = 5 * tile * scale + _MARGIN
        raw = base64.b64decode(image.to_image_content().data)
        decoded = PILImage.open(BytesIO(raw))
        assert decoded.size == (expected_w, expected_h)

    def test_region_exceeding_sheet_is_a_clean_error(self, tmp_project):
        sheet = tmp_project / "sheet.png"
        _make_sheet(sheet, 4, 4, tile=8)
        result = procgen.atlas_grid("res://sheet.png", tile_size=8, region="0:10,0:2")
        assert isinstance(result, str)
        assert result.startswith("ERROR")

    def test_malformed_region_is_a_clean_error_not_a_crash(self, tmp_project):
        sheet = tmp_project / "sheet.png"
        _make_sheet(sheet, 4, 4, tile=8)
        result = procgen.atlas_grid("res://sheet.png", region="not-a-region")
        assert isinstance(result, str)
        assert result.startswith("ERROR")


# ---------------------------------------------------------------------------
# containment + graceful errors
# ---------------------------------------------------------------------------


class TestAtlasGridErrors:
    def test_dotdot_escape_refused(self, tmp_project):
        result = procgen.atlas_grid("../../etc/passwd")
        assert isinstance(result, str)
        assert result.startswith("Refused:")
        assert "resolves outside the project root" in result

    def test_absolute_outside_path_refused(self, tmp_project, tmp_path_factory):
        outside = tmp_path_factory.mktemp("outside") / "secret.png"
        outside.write_bytes(b"not a real png")
        result = procgen.atlas_grid(str(outside))
        assert isinstance(result, str)
        assert result.startswith("Refused:")

    def test_missing_file_is_a_clean_error(self, tmp_project):
        result = procgen.atlas_grid("res://does_not_exist.png")
        assert isinstance(result, str)
        assert result.startswith("Not found:")

    def test_not_a_png_is_a_clean_error(self, tmp_project):
        bogus = tmp_project / "bogus.png"
        bogus.write_text("this is not a png", encoding="utf-8")
        result = procgen.atlas_grid("res://bogus.png")
        assert isinstance(result, str)
        assert result.startswith("ERROR")

    def test_valid_non_png_image_is_rejected(self, tmp_project):
        """A real, openable JPEG saved with a .png extension must be rejected
        by format, not silently accepted just because PIL can open it."""
        jpeg_as_png = tmp_project / "actually_jpeg.png"
        im = PILImage.new("RGB", (16, 16), (255, 0, 0))
        im.save(jpeg_as_png, format="JPEG")

        result = procgen.atlas_grid("res://actually_jpeg.png")
        assert isinstance(result, str)
        assert result.startswith("ERROR")
        assert "PNG" in result
        assert "JPEG" in result

    def test_non_positive_tile_size_is_a_clean_error(self, tmp_project):
        sheet = tmp_project / "sheet.png"
        _make_sheet(sheet, 4, 4, tile=8)
        result = procgen.atlas_grid("res://sheet.png", tile_size=0)
        assert isinstance(result, str)
        assert result.startswith("ERROR")

    def test_non_positive_scale_is_a_clean_error(self, tmp_project):
        sheet = tmp_project / "sheet.png"
        _make_sheet(sheet, 4, 4, tile=8)
        result = procgen.atlas_grid("res://sheet.png", scale=0)
        assert isinstance(result, str)
        assert result.startswith("ERROR")

    def test_directory_path_is_a_clean_error(self, tmp_project):
        """A path that resolves to a directory (not a file) must not crash
        PIL.Image.open — 'Not found' is the correct, clean response."""
        d = tmp_project / "a_directory.png"
        d.mkdir()
        result = procgen.atlas_grid("res://a_directory.png")
        assert isinstance(result, str)
        assert result.startswith("Not found:")


# ---------------------------------------------------------------------------
# image content carries real data (not just a path)
# ---------------------------------------------------------------------------


class TestAtlasGridReturnsImageContent:
    def test_returns_image_content_with_real_png_bytes(self, tmp_project):
        sheet = tmp_project / "sheet.png"
        _make_sheet(sheet, 4, 4, tile=8)
        result = procgen.atlas_grid("res://sheet.png")
        assert isinstance(result, list)
        assert len(result) == 2
        summary, image = result
        assert isinstance(summary, str)
        content = image.to_image_content()
        assert content.mimeType == "image/png"
        assert len(content.data) > 0  # base64 payload is non-empty

    def test_server_tool_delegates_identically(self, tmp_project):
        """server.procgen_atlas_grid is a thin delegate to procgen.atlas_grid."""
        from godot_mcp.server import procgen_atlas_grid

        sheet = tmp_project / "sheet.png"
        _make_sheet(sheet, 4, 4, tile=8)
        result = procgen_atlas_grid("res://sheet.png")
        assert isinstance(result, list)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# real FastMCP call path — proves structured_output=False actually prevents
# the unsafe auto structured-output conversion of a [str, Image] list, which
# calling the plain function directly (above) cannot detect.
# ---------------------------------------------------------------------------


class TestAtlasGridThroughRealMCPPath:
    def test_call_tool_returns_text_and_image_content_not_structured_json(self, tmp_project):
        """Goes through mcp.call_tool (FastMCP's real dispatch, the same path
        a real MCP client uses), not the bare server function. This is the
        only way to catch the structured-output auto-conversion FastMCP runs
        after _convert_to_content for tools with a bare str|list annotation —
        calling procgen_atlas_grid() directly bypasses that step entirely."""
        from godot_mcp.server import mcp

        sheet = tmp_project / "sheet.png"
        _make_sheet(sheet, 4, 4, tile=8)

        result = asyncio.run(mcp.call_tool("procgen_atlas_grid", {"sheet_path": "res://sheet.png"}))

        # Must be the unstructured content sequence, not a structured dict.
        assert isinstance(result, list)
        assert len(result) == 2

        text_block, image_block = result
        assert isinstance(text_block, TextContent)
        assert "Atlas grid" in text_block.text

        assert isinstance(image_block, ImageContent)
        assert image_block.mimeType == "image/png"
        raw = base64.b64decode(image_block.data)
        decoded = PILImage.open(BytesIO(raw))
        assert decoded.format == "PNG"

    def test_call_tool_error_string_stays_a_single_text_block(self, tmp_project):
        """The error-path return (a plain string) must still come back as one
        TextContent block through the real dispatch, unaffected by disabling
        structured output for the success-path list return."""
        from godot_mcp.server import mcp

        result = asyncio.run(mcp.call_tool("procgen_atlas_grid", {"sheet_path": "res://does_not_exist.png"}))

        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert result[0].text.startswith("Not found:")
