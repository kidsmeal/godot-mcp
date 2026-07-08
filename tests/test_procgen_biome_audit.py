"""Phase 3 of biome-world.plan.md: the §3.4 investigation, resolved.

QUESTION: does `procgen_terrain_audit` need to report biome-set/transition
coverage the way it reports single-terrain coverage, or does the existing
per-terrain-set audit already cover every biome role?

RESOLUTION: NO — no `procgen.py` change is made. Reasoning:

1. Phase 2 already made each biome emit TWO single-terrain terrain sets
   (`{biome}_panel`, `{biome}_coast`). `_audit_report`'s per-terrain-set
   coverage loop scopes `tiles_in_set` strictly by `t["terrain_set"] == tsi`
   (see `src/godot_mcp/procgen.py`), so a biome-set tileset already audits as
   N independent single-terrain rows — exactly the same machinery a plain v2
   multi-terrain-set tileset gets, with no biome-aware branch needed.

2. The design (`biome-world.md` §2) pins NO per-biome-PAIR transition
   contract for the tools to audit: "for a cell of biome X draw each
   higher-priority neighbor biome Y's transition block ... Multi-biome
   junctions resolve per corner ... No special-case junction logic," and
   the transition panel's "outside" is uniformly transparent (the lower
   biome shows through) — it carries NO identity for biome X at all. So one
   panel-art class exists PER HIGHER BIOME Y, used against ANY lower
   neighbor, never a (X, Y) pair. This is the same reasoning §2 states
   explicitly for water ("Water is one unified blue ... need no
   per-biome-pair edges"), and it holds symmetrically for land-land panels:
   there is no pair-level coverage contract for an audit to express, because
   there is no pair-level art to cover.

3. Therefore "biome-set coverage" reduces to "coverage of each biome's own
   panel/coastline terrain set," which the existing per-terrain-set loop
   already reports, one row per terrain set, with no cross-set aggregation
   needed on top.

This file is the evidence for that resolution, proven two ways against a
REAL headless build (never a synthetic Python dict — the fixture from
`TestTwoBiomeMultiBiomeBuildAndAudit` in `tests/test_procgen_biome_build.py`,
extended here with a deliberate gap):

  - `TestCleanMultiBiomeAuditsEachRoleIndependently`: a normal two-biome
    (`desert > swamp`) tileset audits all 4 role terrain sets, each complete
    for what its own block actually depicts, in ONE `terrain_audit()` call.

  - `TestGapInOneRoleIsFlaggedNotMaskedBySiblingRoleOrBiome`: the CRITICAL
    negative case. One land cell is deliberately omitted from `desert_panel`
    ONLY. The exact same signature class is fully covered by `desert_coast`
    (sibling role, same biome — the precise defect the Phase 2 amendment
    fixed when panel/coastline shared one terrain) AND by `swamp_panel`
    (sibling biome, same role). The audit must still report the gap as
    MISSING under `desert_panel`'s own coverage entry, in the SAME audit run
    that reports the other three terrain sets clean-for-their-fixture — proof
    that no terrain set's coverage is silently filled in by another's tiles.

Binary-gated: skipped when no Godot binary resolves, same guard as
`test_procgen_biome_build.py`.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from godot_mcp import config, procgen, runner

_godot_available = bool(config.resolve_godot() and Path(config.resolve_godot()[0]).exists())

# The minifantasy_edges 3x5 block's 14 LAND cells (excludes the water-center
# (1,1), which is never painted here — panels stay transparent-outside by
# design; coastline blocks separately paint their own opaque "outside").
_LAND_CELLS: list[tuple[int, int]] = [
    (0, 0), (1, 0), (2, 0),
    (0, 1),         (2, 1),
    (0, 2), (1, 2), (2, 2),
    (0, 3), (1, 3), (2, 3),
    (0, 4), (1, 4), (2, 4),
]


def _land_cells_literal(cells: list[tuple[int, int]]) -> str:
    return "[" + ", ".join(f"Vector2i({x},{y})" for x, y in cells) + "]"


def _make_two_biome_fixture_source(gap: tuple[int, int] | None) -> str:
    """GDScript source for a ONE-atlas, FOUR-block two-biome (desert > swamp)
    fixture: origin 0 = desert_panel (transparent outside), origin 3 =
    desert_coastline (opaque outside), origin 6 = swamp_panel (transparent
    outside), origin 9 = swamp_coastline (opaque outside) — the identical
    layout `TestTwoBiomeMultiBiomeBuildAndAudit` in test_procgen_biome_build.py
    builds for Phase 2's B1 confirm.

    `gap`, when given, is a single block-relative land cell OMITTED from
    origin 0 (desert_panel) ONLY — every other block always paints its full
    14-cell land footprint. This is the deliberately-missing-transition-class
    fixture the negative-case test needs; `gap=None` reproduces the plain
    Phase 2 fixture exactly.
    """
    desert_panel_cells = [c for c in _LAND_CELLS if c != gap] if gap is not None else _LAND_CELLS
    return f"""extends SceneTree
func _initialize() -> void:
\tvar w := 96
\tvar h := 40
\tvar img := Image.create(w, h, false, Image.FORMAT_RGBA8)
\timg.fill(Color(0, 0, 0, 0))
\tvar full_land_cells := {_land_cells_literal(_LAND_CELLS)}
\tvar desert_panel_cells := {_land_cells_literal(desert_panel_cells)}
\tvar coastline_origins := [3, 9]
\tvar outside_col := Color(0.25, 0.44, 0.82, 1.0)
\tfor ox in coastline_origins:
\t\tfor gy in range(5):
\t\t\tfor gx in range(3):
\t\t\t\t_fill_cell(img, ox + gx, gy, outside_col)
\tfor c in desert_panel_cells:
\t\t_fill_cell(img, 0 + c.x, c.y, Color(0.3, 0.6, 0.2, 1.0))
\tfor ox in [3, 6, 9]:
\t\tfor c in full_land_cells:
\t\t\t_fill_cell(img, ox + c.x, c.y, Color(0.3, 0.6, 0.2, 1.0))
\tvar err := img.save_png(OS.get_environment("PROCGEN_FIXTURE_OUT"))
\tprint("FIXTURE_SAVE_RC=" + str(err))
\tquit(0)

func _fill_cell(img: Image, gx: int, gy: int, col: Color) -> void:
\tfor py in range(8):
\t\tfor px in range(8):
\t\t\timg.set_pixel(gx * 8 + px, gy * 8 + py, col)
"""


def _two_biome_config(texture_res: str) -> dict:
    return {
        "tileset": {"tile_size": [8, 8]},
        "atlas": [{"id": "ground", "texture": texture_res, "scan": "non_transparent"}],
        "biome_priority": ["desert", "swamp"],
        "biome": [
            {"name": "desert", "atlas": "ground", "panel": {"origin": [0, 0]}, "coastline": {"origin": [3, 0]}},
            {"name": "swamp", "atlas": "ground", "panel": {"origin": [6, 0]}, "coastline": {"origin": [9, 0]}},
        ],
    }


@pytest.fixture()
def tmp_project(tmp_path_factory, monkeypatch):
    proj = tmp_path_factory.mktemp("procgen_biome_audit_proj")
    (proj / "project.godot").write_text(
        'config_version=5\n\n[application]\nconfig/name="ProcgenBiomeAuditFixture"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "PROJECT_ROOT", proj)
    return proj


def _make_fixture_atlas(proj: Path, monkeypatch, filename: str, gap: tuple[int, int] | None) -> str:
    art = proj / "art"
    art.mkdir(parents=True, exist_ok=True)
    out_png = art / filename
    monkeypatch.setenv("PROCGEN_FIXTURE_OUT", str(out_png))
    r = runner.run_temp_probe(_make_two_biome_fixture_source(gap), timeout=60)
    assert r.get("rc") == 0, f"fixture generation failed: {r}"
    assert out_png.exists(), f"fixture PNG not written: {r.get('out')}"
    return f"res://art/{filename}"


@pytest.mark.skipif(not _godot_available, reason="Godot binary not resolvable on this machine")
class TestCleanMultiBiomeAuditsEachRoleIndependently:
    """The positive half of the §3.4 resolution: on a normal (non-gapped)
    two-biome tileset, the EXISTING per-terrain-set coverage loop already
    reports all 4 role terrain sets (`desert_panel`, `desert_coast`,
    `swamp_panel`, `swamp_coast`) completely and independently in ONE
    `terrain_audit()` call — no biome-set-level summary needed on top."""

    def test_two_biome_tileset_audits_all_four_roles_independently(self, tmp_project, tmp_path, monkeypatch):
        texture_res = _make_fixture_atlas(tmp_project, monkeypatch, "clean_two_biome.png", gap=None)
        cfg_path = tmp_path / "clean_two_biome.json"
        cfg_path.write_text(json.dumps(_two_biome_config(texture_res)), encoding="utf-8")

        build_result = procgen.tileset_build(str(cfg_path), "res://tilesets/clean_two_biome.tres")
        assert build_result.startswith("OK"), build_result
        assert "tiles: 58" in build_result, build_result
        assert "terrain sets: 4" in build_result, build_result

        audit_result = procgen.terrain_audit("res://tilesets/clean_two_biome.tres")
        assert "CLEAN" in audit_result, audit_result
        assert "ERRORS" not in audit_result, audit_result
        assert "| 0 | desert_panel | MATCH_CORNERS | 16 | 14 | 2 | 0 |" in audit_result, audit_result
        assert "| 1 | desert_coast | MATCH_CORNERS | 16 | 15 | 1 | 0 |" in audit_result, audit_result
        assert "| 2 | swamp_panel | MATCH_CORNERS | 16 | 14 | 2 | 0 |" in audit_result, audit_result
        assert "| 3 | swamp_coast | MATCH_CORNERS | 16 | 15 | 1 | 0 |" in audit_result, audit_result

        fenced = audit_result.split("```json", 1)[1].split("```", 1)[0]
        coverage = json.loads(fenced)
        assert set(coverage.keys()) == {"0", "1", "2", "3"}
        # each role's coverage stands on its own tiles; no cross-role sharing
        for tsi in ("0", "1", "2", "3"):
            assert coverage[tsi]["variants"] == {}, coverage[tsi]


@pytest.mark.skipif(not _godot_available, reason="Godot binary not resolvable on this machine")
class TestGapInOneRoleIsFlaggedNotMaskedBySiblingRoleOrBiome:
    """The CRITICAL negative case. One land cell is deliberately omitted from
    `desert_panel` ONLY. The exact same signature class is fully covered by
    `desert_coast` (sibling role, same biome — the precise defect the Phase 2
    amendment fixed) and by `swamp_panel` (sibling biome, same role). Proves
    the existing per-terrain-set audit does NOT let either sibling mask the
    gap in a single `terrain_audit()` run — the evidence that no biome-set-
    aware audit change is needed."""

    def test_deliberately_missing_panel_class_is_flagged_not_masked(self, tmp_project, tmp_path, monkeypatch):
        gap_cell = (2, 0)
        gap_key = procgen._sig_key(procgen.minifantasy_edges_table()[gap_cell])

        texture_res = _make_fixture_atlas(tmp_project, monkeypatch, "gap_two_biome.png", gap=gap_cell)
        cfg_path = tmp_path / "gap_two_biome.json"
        cfg_path.write_text(json.dumps(_two_biome_config(texture_res)), encoding="utf-8")

        build_result = procgen.tileset_build(str(cfg_path), "res://tilesets/gap_two_biome.tres")
        assert build_result.startswith("OK"), build_result
        # desert_panel loses exactly 1 of its 14 land cells (13 remain); the
        # other 3 role blocks are untouched: 13 + 15 + 14 + 15 = 57 tiles.
        assert "tiles: 57" in build_result, build_result
        assert "terrain sets: 4" in build_result, build_result

        audit_result = procgen.terrain_audit("res://tilesets/gap_two_biome.tres")
        # missing coverage is informational, not a law violation — still CLEAN.
        assert "CLEAN" in audit_result, audit_result
        assert "ERRORS" not in audit_result, audit_result
        assert "| 0 | desert_panel | MATCH_CORNERS | 16 | 13 | 3 | 0 |" in audit_result, audit_result
        assert "| 1 | desert_coast | MATCH_CORNERS | 16 | 15 | 1 | 0 |" in audit_result, audit_result
        assert "| 2 | swamp_panel | MATCH_CORNERS | 16 | 14 | 2 | 0 |" in audit_result, audit_result
        assert "| 3 | swamp_coast | MATCH_CORNERS | 16 | 15 | 1 | 0 |" in audit_result, audit_result

        fenced = audit_result.split("```json", 1)[1].split("```", 1)[0]
        coverage = json.loads(fenced)
        assert coverage["0"]["terrain_name"] == "desert_panel"
        assert coverage["1"]["terrain_name"] == "desert_coast"
        assert coverage["2"]["terrain_name"] == "swamp_panel"
        assert coverage["3"]["terrain_name"] == "swamp_coast"

        # THE negative-case proof: desert_panel is missing the gap class —
        # a normal panel is already missing 2 classes (empty + full-interior);
        # the gap adds a THIRD, isolated to desert_panel alone.
        assert gap_key in coverage["0"]["missing"], coverage["0"]
        assert len(coverage["0"]["missing"]) == 3, coverage["0"]["missing"]

        # ...while desert's OWN coastline (sibling role, same biome) covers
        # it — this is exactly the pre-Phase-2-fix masking scenario (panel and
        # coastline sharing one terrain); with roles split, desert_coast's
        # coverage of this class must NOT erase desert_panel's own gap above.
        assert gap_key not in coverage["1"]["missing"], coverage["1"]
        assert gap_key in coverage["1"]["signatures"], coverage["1"]["signatures"].keys()
        assert len(coverage["1"]["missing"]) == 1, coverage["1"]["missing"]

        # ...and swamp's panel (sibling biome, same role) ALSO covers it,
        # and is otherwise a completely standard, untouched panel — proving
        # the gap is isolated to desert_panel, not a systemic miscount from
        # splitting the fixture into 4 blocks.
        assert gap_key not in coverage["2"]["missing"], coverage["2"]
        assert gap_key in coverage["2"]["signatures"], coverage["2"]["signatures"].keys()
        assert len(coverage["2"]["missing"]) == 2, coverage["2"]["missing"]

        assert len(coverage["3"]["missing"]) == 1, coverage["3"]["missing"]
