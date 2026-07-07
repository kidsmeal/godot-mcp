"""Offline tests for the v3 biome-set config shape (Phase 1 of biome-world.plan.md).

No real Godot binary required — these exercise validate_config's normalization
of a declarative `[[biome]]` roster (priority-ordered biomes, each with a
`minifantasy_edges` transition-panel terrain_assign and a coastline
terrain_assign) into the EXISTING `terrain_set`/`terrain_assign` config shape
`compose_build_script` already knows how to consume — no builder code change,
per the plan's grounding. The live headless build proving transparent-outside
== opaque-outside is `test_procgen_biome_build.py` (skipped when Godot is
unavailable).
"""
from __future__ import annotations

import json

import pytest

from godot_mcp import procgen


def _plan_from_source(src: str) -> dict:
    """Extract the resolved plan dict compose_build_script embeds as the
    PLAN_JSON string literal (duplicated from test_procgen.py's helper of the
    same name/shape — a small pure-parsing helper, not worth a cross-test-file
    import)."""
    marker = "const PLAN_JSON := "
    line = next(ln for ln in src.splitlines() if ln.startswith(marker))
    outer = json.loads(line[len(marker) :])
    return json.loads(outer)


def _base_cfg() -> dict:
    return {
        "tileset": {"tile_size": [8, 8]},
        "atlas": [{"id": "ground", "texture": "res://art/ground.png", "scan": "non_transparent"}],
    }


def _one_biome_cfg(name: str = "plains") -> dict:
    cfg = _base_cfg()
    cfg["biome_priority"] = [name]
    cfg["biome"] = [
        {
            "name": name,
            "atlas": "ground",
            "panel": {"origin": [0, 0]},
            "coastline": {"origin": [3, 0]},
        }
    ]
    return cfg


class TestBiomeSetConfigNormalizes:
    """A valid biome-set config normalizes into the pre-existing
    terrain_set/terrain_assign shape, unchanged from what compose_build_script
    already consumes."""

    def test_single_biome_normalizes_to_one_terrain_set(self):
        cfg = procgen.validate_config(_one_biome_cfg("plains"))
        terrain_sets = cfg.get("terrain_set") or []
        assert len(terrain_sets) == 1
        assert terrain_sets[0]["mode"] == "match_corners"
        assert [t["name"] for t in terrain_sets[0]["terrains"]] == ["plains"]

    def test_single_biome_normalizes_to_panel_and_coastline_terrain_assigns(self):
        cfg = procgen.validate_config(_one_biome_cfg("plains"))
        assigns = cfg.get("terrain_assign") or []
        assert len(assigns) == 2
        for asn in assigns:
            assert asn["strategy"] == "minifantasy_edges"
            assert asn["terrain"] == "plains"
            assert asn["atlas"] == "ground"
        origins = sorted(tuple(a["origin"]) for a in assigns)
        assert origins == [(0, 0), (3, 0)]

    def test_normalized_assigns_resolve_bits_through_existing_helper_unchanged(self):
        """The panel and coastline assigns both resolve through
        `_resolve_assign_bits` exactly like any hand-written minifantasy_edges
        assign — this is the "no new strategy table" claim proven directly."""
        cfg = procgen.validate_config(_one_biome_cfg("plains"))
        assigns = cfg.get("terrain_assign") or []
        panel = next(a for a in assigns if tuple(a["origin"]) == (0, 0))
        coastline = next(a for a in assigns if tuple(a["origin"]) == (3, 0))
        panel_bits = procgen._resolve_assign_bits(panel, tuple(panel["origin"]))
        coastline_bits = procgen._resolve_assign_bits(coastline, tuple(coastline["origin"]))
        assert len(panel_bits) == 15
        assert len(coastline_bits) == 15
        # translated to their own origins, not overlapping
        assert set(panel_bits) == {(0 + c, 0 + r) for c in range(3) for r in range(5)}
        assert set(coastline_bits) == {(3 + c, 0 + r) for c in range(3) for r in range(5)}

    def test_compose_build_script_accepts_the_normalized_config_unchanged(self):
        """No compose_build_script code path changed for Phase 1 — proven by
        driving it directly with a normalized biome-set config and confirming
        it composes without needing any biome-aware branch."""
        cfg = procgen.validate_config(_one_biome_cfg("plains"))
        src = procgen.compose_build_script(cfg, "res://out/ts.tres", "biome1")
        assert "extends SceneTree" in src
        # the plan JSON is embedded as an escaped string literal
        assert "plains" in src
        plan = _plan_from_source(src)
        assert plan["terrain_index"]["plains"] == [0, 0]


class TestBiomePriorityOrderPreserved:
    def test_priority_order_round_trips(self):
        cfg = _base_cfg()
        cfg["biome_priority"] = ["desert", "ice", "swamp", "plains"]
        cfg["biome"] = [
            {"name": n, "atlas": "ground", "panel": {"origin": [i * 10, 0]}, "coastline": {"origin": [i * 10, 10]}}
            for i, n in enumerate(["desert", "ice", "swamp", "plains"])
        ]
        normalized = procgen.validate_config(cfg)
        assert normalized["biome_priority"] == ["desert", "ice", "swamp", "plains"]

    def test_priority_order_need_not_match_roster_declaration_order(self):
        cfg = _base_cfg()
        cfg["biome_priority"] = ["ice", "desert"]
        cfg["biome"] = [
            {"name": "desert", "atlas": "ground", "panel": {"origin": [0, 0]}, "coastline": {"origin": [0, 10]}},
            {"name": "ice", "atlas": "ground", "panel": {"origin": [10, 0]}, "coastline": {"origin": [10, 10]}},
        ]
        normalized = procgen.validate_config(cfg)
        assert normalized["biome_priority"] == ["ice", "desert"]


class TestBiomeRosterErrors:
    def test_missing_biome_in_priority_errors(self):
        """A priority entry naming a biome absent from the roster errors."""
        cfg = _one_biome_cfg("plains")
        cfg["biome_priority"] = ["plains", "desert"]  # desert never declared in [[biome]]
        with pytest.raises(procgen.ConfigError, match="unknown biome"):
            procgen.validate_config(cfg)

    def test_duplicate_biome_name_in_roster_errors(self):
        cfg = _base_cfg()
        cfg["biome_priority"] = ["plains"]
        cfg["biome"] = [
            {"name": "plains", "atlas": "ground", "panel": {"origin": [0, 0]}, "coastline": {"origin": [0, 10]}},
            {"name": "plains", "atlas": "ground", "panel": {"origin": [20, 0]}, "coastline": {"origin": [20, 10]}},
        ]
        with pytest.raises(procgen.ConfigError, match="duplicate biome"):
            procgen.validate_config(cfg)

    def test_biome_missing_from_priority_errors(self):
        """Every declared biome must appear in the priority roster — an
        orphaned [[biome]] entry with no priority ranking is rejected rather
        than silently dropped."""
        cfg = _base_cfg()
        cfg["biome_priority"] = ["plains"]
        cfg["biome"] = [
            {"name": "plains", "atlas": "ground", "panel": {"origin": [0, 0]}, "coastline": {"origin": [0, 10]}},
            {"name": "desert", "atlas": "ground", "panel": {"origin": [20, 0]}, "coastline": {"origin": [20, 10]}},
        ]
        with pytest.raises(procgen.ConfigError, match="missing from biome_priority"):
            procgen.validate_config(cfg)

    def test_biome_missing_name_errors(self):
        cfg = _base_cfg()
        cfg["biome_priority"] = [""]
        cfg["biome"] = [{"atlas": "ground", "panel": {"origin": [0, 0]}, "coastline": {"origin": [0, 10]}}]
        with pytest.raises(procgen.ConfigError, match="needs a string name"):
            procgen.validate_config(cfg)

    def test_biome_unknown_atlas_errors(self):
        cfg = _base_cfg()
        cfg["biome_priority"] = ["plains"]
        cfg["biome"] = [{"name": "plains", "atlas": "nope", "panel": {"origin": [0, 0]}, "coastline": {"origin": [0, 10]}}]
        with pytest.raises(procgen.ConfigError, match="unknown atlas"):
            procgen.validate_config(cfg)

    def test_biome_missing_panel_errors(self):
        cfg = _base_cfg()
        cfg["biome_priority"] = ["plains"]
        cfg["biome"] = [{"name": "plains", "atlas": "ground", "coastline": {"origin": [0, 10]}}]
        with pytest.raises(procgen.ConfigError, match="needs a `panel`"):
            procgen.validate_config(cfg)

    def test_biome_missing_coastline_errors(self):
        cfg = _base_cfg()
        cfg["biome_priority"] = ["plains"]
        cfg["biome"] = [{"name": "plains", "atlas": "ground", "panel": {"origin": [0, 0]}}]
        with pytest.raises(procgen.ConfigError, match="needs a `coastline`"):
            procgen.validate_config(cfg)

    def test_biome_panel_and_coastline_origin_must_be_int_pair(self):
        cfg = _base_cfg()
        cfg["biome_priority"] = ["plains"]
        cfg["biome"] = [{"name": "plains", "atlas": "ground", "panel": {"origin": [0]}, "coastline": {"origin": [0, 10]}}]
        with pytest.raises(procgen.ConfigError, match="origin"):
            procgen.validate_config(cfg)


class TestBiomeSetSameBiomeBothAssignsValidate:
    """A transition-panel assign and a coastline assign on the SAME biome both
    validate and both resolve — the exit criterion's explicit phrasing."""

    def test_both_panel_and_coastline_resolve_for_one_biome(self):
        cfg = procgen.validate_config(_one_biome_cfg("plains"))
        assigns = cfg.get("terrain_assign") or []
        assert all(a["terrain"] == "plains" for a in assigns)
        assert len(assigns) == 2
        panel, coastline = assigns
        bits_a = procgen._resolve_assign_bits(panel, tuple(panel["origin"]))
        bits_b = procgen._resolve_assign_bits(coastline, tuple(coastline["origin"]))
        # each is a full 15-cell minifantasy_edges block, independently resolved
        assert len(bits_a) == 15
        assert len(bits_b) == 15

    def test_biome_panel_and_coastline_may_each_carry_their_own_interior(self):
        """Panel/coastline blocks may each declare an `interior` fill list
        (same shape existing minifantasy_edges assigns accept) so a biome's
        solid ground interior and its coastline's solid "all-land" interior
        (if ever needed) are independently expressible."""
        cfg = _base_cfg()
        cfg["biome_priority"] = ["plains"]
        cfg["biome"] = [
            {
                "name": "plains",
                "atlas": "ground",
                "panel": {"origin": [0, 0], "interior": [[3, 0], [3, 1, 0.5]]},
                "coastline": {"origin": [3, 6]},
            }
        ]
        normalized = procgen.validate_config(cfg)
        assigns = normalized.get("terrain_assign") or []
        panel = next(a for a in assigns if tuple(a["origin"]) == (0, 0))
        assert panel.get("interior") == [[3, 0], [3, 1, 0.5]]

    def test_biome_panel_interior_malformed_is_a_clean_config_error(self):
        cfg = _base_cfg()
        cfg["biome_priority"] = ["plains"]
        cfg["biome"] = [
            {
                "name": "plains",
                "atlas": "ground",
                "panel": {"origin": [0, 0], "interior": [[3]]},
                "coastline": {"origin": [3, 6]},
            }
        ]
        with pytest.raises(procgen.ConfigError, match="interior must be"):
            procgen.validate_config(cfg)


class TestBiomeSetCoexistsWithPlainTerrainConfig:
    def test_config_with_no_biome_key_is_unaffected(self):
        """A plain v2 config with no `[[biome]]` section at all must validate
        and normalize identically to before — the biome-set shape is purely
        additive/opt-in."""
        cfg = _base_cfg()
        cfg["terrain_set"] = [{"mode": "match_corners", "terrains": [{"name": "grass"}]}]
        cfg["terrain_assign"] = [{"atlas": "ground", "strategy": "minifantasy_edges", "terrain": "grass", "origin": [0, 0]}]
        normalized = procgen.validate_config(cfg)
        assert normalized["terrain_set"] == cfg["terrain_set"]
        assert normalized["terrain_assign"] == cfg["terrain_assign"]
        assert "biome_priority" not in normalized

    def test_biome_roster_appends_to_any_pre_existing_terrain_config(self):
        """A config may combine a hand-written v2 terrain_set/terrain_assign
        with a [[biome]] roster; the biome-derived entries append rather than
        clobber the pre-existing ones."""
        cfg = _one_biome_cfg("plains")
        cfg["terrain_set"] = [{"mode": "match_sides", "terrains": [{"name": "decor"}]}]
        cfg["terrain_assign"] = [{"atlas": "ground", "strategy": "blob16_sides", "terrain": "decor"}]
        normalized = procgen.validate_config(cfg)
        names = [t["name"] for ts in normalized["terrain_set"] for t in ts["terrains"]]
        assert names == ["decor", "plains"]
        assert len(normalized["terrain_assign"]) == 3  # 1 hand-written + 2 biome-derived
