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

    def test_single_biome_normalizes_to_two_role_terrain_sets(self):
        """FIX (2026-07-08 amendment): one biome emits TWO single-terrain
        terrain sets, one per draw-pass role — `plains_panel` and
        `plains_coast` — never one merged terrain shared by both roles."""
        cfg = procgen.validate_config(_one_biome_cfg("plains"))
        terrain_sets = cfg.get("terrain_set") or []
        assert len(terrain_sets) == 2
        assert all(ts["mode"] == "match_corners" for ts in terrain_sets)
        assert all(len(ts["terrains"]) == 1 for ts in terrain_sets)  # v2's one-terrain-per-set rule holds per role
        names = [t["name"] for ts in terrain_sets for t in ts["terrains"]]
        assert names == ["plains_panel", "plains_coast"]

    def test_single_biome_normalizes_to_panel_and_coastline_terrain_assigns(self):
        cfg = procgen.validate_config(_one_biome_cfg("plains"))
        assigns = cfg.get("terrain_assign") or []
        assert len(assigns) == 2
        for asn in assigns:
            assert asn["strategy"] == "minifantasy_edges"
            assert asn["atlas"] == "ground"
        by_origin = {tuple(a["origin"]): a["terrain"] for a in assigns}
        assert by_origin == {(0, 0): "plains_panel", (3, 0): "plains_coast"}

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
        it composes without needing any biome-aware branch. `terrain_index` is
        a plain name -> [terrain_set, terrain] lookup that has never known
        about biomes or roles; it resolves `plains_panel`/`plains_coast` to
        their own terrain sets exactly like any other hand-written name."""
        cfg = procgen.validate_config(_one_biome_cfg("plains"))
        src = procgen.compose_build_script(cfg, "res://out/ts.tres", "biome1")
        assert "extends SceneTree" in src
        # the plan JSON is embedded as an escaped string literal
        assert "plains_panel" in src
        assert "plains_coast" in src
        plan = _plan_from_source(src)
        assert plan["terrain_index"]["plains_panel"] == [0, 0]
        assert plan["terrain_index"]["plains_coast"] == [1, 0]


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
        assert {a["terrain"] for a in assigns} == {"plains_panel", "plains_coast"}
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
        assert names == ["decor", "plains_panel", "plains_coast"]
        assert len(normalized["terrain_assign"]) == 3  # 1 hand-written + 2 biome-derived


def _four_biome_cfg() -> dict:
    """The design's actual roster order (`biome-world.md` §2): desert > ice >
    swamp > plains, highest to lowest priority. Each biome gets its own
    non-overlapping panel/coastline origin band."""
    cfg = _base_cfg()
    names = ["desert", "ice", "swamp", "plains"]
    cfg["biome_priority"] = list(names)
    cfg["biome"] = [
        {"name": n, "atlas": "ground", "panel": {"origin": [i * 10, 0]}, "coastline": {"origin": [i * 10, 10]}}
        for i, n in enumerate(names)
    ]
    return cfg


class TestPhase2PriorityOrderIsStableAndSerialized:
    """Phase 2: the roster's priority order resolves into a stable, serialized
    (plain list[str], JSON-round-trippable) order in the normalized config —
    the ordering itself is decided once, by validate_config, and never
    reshuffled by any downstream consumer (compose_build_script, json.dumps,
    ...)."""

    def test_full_four_biome_priority_matches_design_order(self):
        """`desert > ice > swamp > plains` — the exact roster/priority the
        design (`biome-world.md` §2) locks — round-trips unchanged."""
        normalized = procgen.validate_config(_four_biome_cfg())
        assert normalized["biome_priority"] == ["desert", "ice", "swamp", "plains"]

    def test_priority_order_is_deterministic_across_independent_validations(self):
        """Two structurally-identical-but-distinct config dicts (never the
        same mutated object — validate_config's in-place roster expansion is
        NOT safe to run twice over one dict, by design: see
        `_expand_biome_roster`'s docstring) normalize to byte-identical
        priority order every time."""
        first = procgen.validate_config(_four_biome_cfg())
        second = procgen.validate_config(_four_biome_cfg())
        assert first["biome_priority"] == second["biome_priority"] == ["desert", "ice", "swamp", "plains"]

    def test_priority_order_survives_a_json_round_trip(self):
        """The normalized order is a plain JSON-serializable list, not a set
        or other unordered container — the shape `compose_build_script`'s own
        `json.dumps(plan)` embedding (and any downstream consumer reading the
        config back off disk) depends on."""
        normalized = procgen.validate_config(_four_biome_cfg())
        round_tripped = json.loads(json.dumps(normalized["biome_priority"]))
        assert round_tripped == ["desert", "ice", "swamp", "plains"]

    def test_priority_order_need_not_match_roster_declaration_order_for_four_biomes(self):
        """Priority order is independent config from roster DECLARATION order
        (already proven for 2 biomes in `TestBiomePriorityOrderPreserved`;
        this extends it to the full 4-biome design roster, declared in one
        order and prioritized in a different one)."""
        cfg = _four_biome_cfg()
        cfg["biome"] = list(reversed(cfg["biome"]))  # declare plains..desert
        normalized = procgen.validate_config(cfg)
        assert normalized["biome_priority"] == ["desert", "ice", "swamp", "plains"]
        declared_order = [t["name"] for ts in normalized["terrain_set"] for t in ts["terrains"]]
        assert declared_order == [
            "plains_panel", "plains_coast",
            "swamp_panel", "swamp_coast",
            "ice_panel", "ice_coast",
            "desert_panel", "desert_coast",
        ]


class TestPhase2MultiBiomePanelAndCoastlineBothResolve:
    """Phase 2: for a roster of MORE THAN ONE biome, every biome's panel and
    coastline assign resolves through the existing `_resolve_assign_bits`
    UNCHANGED — no new strategy table, no per-biome special-casing."""

    def test_every_biome_in_a_four_biome_roster_resolves_both_blocks(self):
        cfg = procgen.validate_config(_four_biome_cfg())
        assigns = cfg.get("terrain_assign") or []
        assert len(assigns) == 8  # 4 biomes x (panel + coastline)

        expected_terrains = set()
        for n in ("desert", "ice", "swamp", "plains"):
            expected_terrains |= {f"{n}_panel", f"{n}_coast"}
        terrain_names = {a["terrain"] for a in assigns}
        assert terrain_names == expected_terrains  # each role is its own terrain, never shared

        all_resolved_cells: set[tuple[int, int]] = set()
        for asn in assigns:
            assert asn["strategy"] == "minifantasy_edges"
            resolved = procgen._resolve_assign_bits(asn, tuple(asn["origin"]))
            assert len(resolved) == 15  # the full minifantasy_edges block
            # each assign's cells are wholly disjoint from every OTHER assign's
            # cells — no origin collisions across the 4-biome roster's
            # non-overlapping origin bands
            assert not (resolved.keys() & all_resolved_cells), (
                f"{asn['terrain']} assign at origin {asn['origin']} collides with an earlier assign's cells"
            )
            all_resolved_cells |= resolved.keys()
        assert len(all_resolved_cells) == 15 * 8  # 4 biomes x 2 blocks x 15 cells, no overlap


class TestPhase2RoleSplitTerrainSets:
    """FIX (2026-07-08 amendment): each biome must emit TWO single-terrain
    terrain sets, one per draw-pass role (`{biome}_panel` / `{biome}_coast`),
    so the game can address a biome's PANEL tile for a corner signature
    separately from its COASTLINE tile for the same signature, and so a
    missing class in one role's coverage can never be masked by the other
    role's tile sharing that signature (the pre-fix defect: both roles
    pointed at ONE shared terrain, so every corner signature carried two
    tiles under one terrain set)."""

    def test_each_biome_yields_exactly_two_single_terrain_role_terrain_sets(self):
        cfg = procgen.validate_config(_four_biome_cfg())
        terrain_sets = cfg.get("terrain_set") or []
        assert len(terrain_sets) == 8  # 4 biomes x 2 roles

        for ts in terrain_sets:
            assert len(ts["terrains"]) == 1  # v2's one-terrain-per-set rule holds per role

        names = [t["name"] for ts in terrain_sets for t in ts["terrains"]]
        expected_names = []
        for n in ("desert", "ice", "swamp", "plains"):
            expected_names += [f"{n}_panel", f"{n}_coast"]
        assert names == expected_names

    def test_no_signature_is_shared_across_a_biomes_panel_and_coast_terrain_sets(self):
        """The defect this fix closes: panel and coastline used to point at
        the SAME terrain, so a corner signature covered by either block was
        registered under one shared terrain identity — masking a missing
        class in either role. Now each role is its own terrain: the panel
        assign's terrain differs from the coastline assign's terrain, and
        their resolved atlas cells (hence tiles/signatures) never overlap."""
        cfg = procgen.validate_config(_one_biome_cfg("plains"))
        assigns = cfg.get("terrain_assign") or []
        panel = next(a for a in assigns if tuple(a["origin"]) == (0, 0))
        coastline = next(a for a in assigns if tuple(a["origin"]) == (3, 0))
        assert panel["terrain"] == "plains_panel"
        assert coastline["terrain"] == "plains_coast"
        assert panel["terrain"] != coastline["terrain"]

        panel_cells = procgen._resolve_assign_bits(panel, tuple(panel["origin"]))
        coastline_cells = procgen._resolve_assign_bits(coastline, tuple(coastline["origin"]))
        assert not (panel_cells.keys() & coastline_cells.keys())
        # both roles independently cover the full 15-cell minifantasy_edges
        # signature set — neither role's coverage depends on the other
        assert len(panel_cells) == len(coastline_cells) == 15


class TestPhase2OutOfRosterPriorityEntryErrors:
    """Phase 2: an out-of-roster priority entry errors — extended to a
    multi-biome roster (Phase 1's `test_missing_biome_in_priority_errors`
    already covers the single-biome case)."""

    def test_priority_names_a_biome_absent_from_a_multi_biome_roster(self):
        cfg = _four_biome_cfg()
        cfg["biome_priority"] = ["desert", "ice", "swamp", "plains", "ocean"]  # ocean never declared
        with pytest.raises(procgen.ConfigError, match="unknown biome"):
            procgen.validate_config(cfg)
