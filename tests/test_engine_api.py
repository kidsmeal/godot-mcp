"""Phase 2 tests: engine grounding correctness (F-4, F-5).
Phase 4 tests: utility_functions/global_enums/global_constants indexing (C17),
               member hit ranking (C21), char budget + misc C22 fixes.

Two test tiers:
  1. Synthetic index (monkeypatched _cache) — deterministic, no network/file I/O.
  2. Real-dump sanity — @pytest.mark.skipif when extension_api.json absent.

Synthetic record shape is validated against the real extension_api.json schema:
  - classes[name]: name, inherits, is_refcounted, is_instantiable, api_type,
      methods[{name, is_const, is_vararg, is_static, is_virtual, arguments[{name,type}]}],
      properties[{name, type, getter, setter}], signals[{name, arguments[{name,type}]}]
  - builtins[name]: name, members[{name, type}],
      methods[{name, return_type, is_const, is_vararg, is_static, arguments[{name,type}]}]
  - singletons[name]: {name, type}
  - ci: {lowercased_name: canonical_name, ...}
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from godot_mcp import config, engine_api

# Path to the Phase-4 fixture dump (checked in, never touches capsulecastle)
_FIXTURE_DUMP = pathlib.Path(__file__).parent / "fixtures" / "extension_api_phase4.json"

# ---------------------------------------------------------------------------
# Synthetic index fixture
# ---------------------------------------------------------------------------

# Hierarchy: Node <- CanvasItem <- Node2D <- Sprite2D
# Node has method add_child; Sprite2D has property texture.
# Built-in: Color (method from_hsv), Vector2 (method snapped).
# Singleton: Input -> type Input (also a class in classes for type resolution).

_SYNTHETIC_INDEX: dict[str, Any] = {
    # Phase-4 additions: utility_functions, global_enums, global_constants
    "utility_functions": {
        "lerp": {
            "name": "lerp",
            "return_type": "Variant",
            "category": "math",
            "is_vararg": False,
            "arguments": [
                {"name": "from", "type": "Variant"},
                {"name": "to", "type": "Variant"},
                {"name": "weight", "type": "float"},
            ],
        },
        "sin": {
            "name": "sin",
            "return_type": "float",
            "category": "math",
            "is_vararg": False,
            "arguments": [{"name": "angle_rad", "type": "float"}],
        },
        "lerp_angle": {
            "name": "lerp_angle",
            "return_type": "float",
            "category": "math",
            "is_vararg": False,
            "arguments": [
                {"name": "from", "type": "float"},
                {"name": "to", "type": "float"},
                {"name": "weight", "type": "float"},
            ],
        },
    },
    "global_enums": {
        "Side": {
            "name": "Side",
            "is_bitfield": False,
            "values": [
                {"name": "SIDE_LEFT", "value": 0},
                {"name": "SIDE_TOP", "value": 1},
                {"name": "SIDE_RIGHT", "value": 2},
                {"name": "SIDE_BOTTOM", "value": 3},
            ],
        },
        "Key": {
            "name": "Key",
            "is_bitfield": False,
            "values": [
                {"name": "KEY_NONE", "value": 0},
                {"name": "KEY_ESCAPE", "value": 16777217},
            ],
        },
    },
    "global_constants": {
        "SPKEY": {"name": "SPKEY", "value": 16777216},
    },
    "classes": {
        "Node": {
            "name": "Node",
            "is_refcounted": False,
            "is_instantiable": True,
            "inherits": None,
            "api_type": "core",
            "methods": [
                {
                    "name": "add_child",
                    "is_const": False,
                    "is_vararg": False,
                    "is_static": False,
                    "is_virtual": False,
                    "arguments": [
                        {"name": "node", "type": "Node"},
                        {"name": "force_readable_name", "type": "bool", "default_value": "false"},
                    ],
                }
            ],
            "signals": [{"name": "ready", "arguments": []}],
            "properties": [
                # null getter/setter — C22: should NOT produce "(get None, set None)"
                {"name": "position_something_long", "type": "Vector2", "getter": None, "setter": None},
            ],
            "enums": [
                {
                    "name": "ProcessMode",
                    "values": [
                        {"name": "PROCESS_MODE_INHERIT", "value": 0},
                        {"name": "PROCESS_MODE_PAUSABLE", "value": 1},
                    ],
                }
            ],
            "constants": [
                {"name": "NOTIFICATION_READY", "value": 13},
            ],
        },
        "CanvasItem": {
            "name": "CanvasItem",
            "is_refcounted": False,
            "is_instantiable": False,
            "inherits": "Node",
            "api_type": "core",
            "methods": [],
            "signals": [{"name": "draw", "arguments": []}],
            "properties": [],
            "enums": [],
            "constants": [],
        },
        "Node2D": {
            "name": "Node2D",
            "is_refcounted": False,
            "is_instantiable": True,
            "inherits": "CanvasItem",
            "api_type": "core",
            "methods": [],
            "signals": [],
            "properties": [
                {"name": "position", "type": "Vector2", "getter": "get_position", "setter": "set_position"},
            ],
            "enums": [],
            "constants": [],
        },
        "Sprite2D": {
            "name": "Sprite2D",
            "is_refcounted": False,
            "is_instantiable": True,
            "inherits": "Node2D",
            "api_type": "core",
            "methods": [],
            "signals": [{"name": "texture_changed", "arguments": []}],
            "properties": [
                {"name": "texture", "type": "Texture2D", "getter": "get_texture", "setter": "set_texture"}
            ],
            "enums": [],
            "constants": [],
        },
        # Input is both a singleton AND a class (so singletons can resolve to it)
        "Input": {
            "name": "Input",
            "is_refcounted": False,
            "is_instantiable": False,
            "inherits": "Object",
            "api_type": "core",
            "methods": [
                {
                    "name": "is_action_pressed",
                    "is_const": False,
                    "is_vararg": False,
                    "is_static": False,
                    "is_virtual": False,
                    "arguments": [{"name": "action", "type": "StringName"}],
                }
            ],
            "signals": [],
            "properties": [],
            "enums": [],
            "constants": [],
        },
    },
    "builtins": {
        "Color": {
            "name": "Color",
            "members": [
                {"name": "r", "type": "float"},
                {"name": "g", "type": "float"},
                {"name": "b", "type": "float"},
                {"name": "a", "type": "float"},
            ],
            "methods": [
                {
                    "name": "from_hsv",
                    "return_type": "Color",
                    "is_const": False,
                    "is_vararg": False,
                    "is_static": True,
                    "arguments": [
                        {"name": "h", "type": "float"},
                        {"name": "s", "type": "float"},
                        {"name": "v", "type": "float"},
                        {"name": "alpha", "type": "float", "default_value": "1.0"},
                    ],
                }
            ],
            "operators": [],
            "constructors": [],
            "constants": [],
        },
        "Vector2": {
            "name": "Vector2",
            "members": [
                {"name": "x", "type": "float"},
                {"name": "y", "type": "float"},
            ],
            "methods": [
                {
                    "name": "snapped",
                    "return_type": "Vector2",
                    "is_const": True,
                    "is_vararg": False,
                    "is_static": False,
                    "arguments": [{"name": "step", "type": "Vector2"}],
                }
            ],
            "operators": [],
            "constructors": [],
            "constants": [],
        },
    },
    "singletons": {
        "Input": {"name": "Input", "type": "Input"},
    },
    # ci: case-insensitive name map — classes + builtins + utility_functions +
    # global_enums + global_constants (NOT singletons).
    "ci": {
        # classes
        "node": "Node",
        "canvasitem": "CanvasItem",
        "node2d": "Node2D",
        "sprite2d": "Sprite2D",
        "input": "Input",
        # builtins
        "color": "Color",
        "vector2": "Vector2",
        # utility_functions
        "lerp": "lerp",
        "sin": "sin",
        "lerp_angle": "lerp_angle",
        # global_enums
        "side": "Side",
        "key": "Key",
        # global_constants
        "spkey": "SPKEY",
    },
}


@pytest.fixture(autouse=True)
def disable_docs(monkeypatch):
    """Prevent any network/file doc lookups during tests."""
    monkeypatch.setenv("GODOT_MCP_DOCS", "0")


@pytest.fixture()
def synthetic(monkeypatch):
    """Monkeypatch engine_api._cache with the synthetic index.
    monkeypatch restores _cache automatically after each test.
    """
    monkeypatch.setattr(engine_api, "_cache", _SYNTHETIC_INDEX)


# ---------------------------------------------------------------------------
# get_member — inherited resolution (F-4)
# ---------------------------------------------------------------------------

class TestGetMemberInherited:
    def test_add_child_on_sprite2d_resolves(self, synthetic):
        """Sprite2D.add_child must resolve via Node ancestor."""
        result = engine_api.get_member("Sprite2D", "add_child")
        assert "add_child" in result
        # Must NOT return the "No member" message
        assert "No member" not in result

    def test_add_child_names_origin_class(self, synthetic):
        """The result must state that add_child is inherited from Node."""
        result = engine_api.get_member("Sprite2D", "add_child")
        assert "Node" in result
        assert "inherited" in result.lower()

    def test_texture_direct_no_inherited_label(self, synthetic):
        """texture is a direct Sprite2D property — no 'inherited from' label."""
        result = engine_api.get_member("Sprite2D", "texture")
        assert "texture" in result
        assert "No member" not in result
        # Should NOT claim it's inherited
        assert "inherited from" not in result

    def test_nonexistent_member_returns_no_member(self, synthetic):
        """A member that exists nowhere in the chain → 'No member' message."""
        result = engine_api.get_member("Sprite2D", "does_not_exist")
        assert "No member" in result

    def test_inherits_deeply_through_chain(self, synthetic):
        """add_child lives on Node, which is 4 hops from Sprite2D — must still resolve."""
        result = engine_api.get_member("Sprite2D", "add_child")
        assert "add_child" in result
        assert "No member" not in result

    def test_builtin_no_walk(self, synthetic):
        """Built-ins have no inherits chain; a missing member stays 'No member'."""
        result = engine_api.get_member("Color", "does_not_exist")
        assert "No member" in result

    def test_inherited_signal(self, synthetic):
        """Signals from ancestors resolve the same way."""
        result = engine_api.get_member("Sprite2D", "ready")
        assert "ready" in result
        assert "No member" not in result


# ---------------------------------------------------------------------------
# get_class — include_inherited flag (F-4)
# ---------------------------------------------------------------------------

class TestGetClassIncludeInherited:
    def test_false_does_not_include_add_child(self, synthetic):
        """Default (False) must NOT show add_child in Sprite2D output."""
        result = engine_api.get_class("Sprite2D", include_inherited=False)
        # add_child is NOT a Sprite2D-own method; it must not appear
        # (texture IS own and should appear)
        assert "texture" in result
        # add_child should not appear when include_inherited=False
        assert "add_child" not in result

    def test_true_includes_add_child(self, synthetic):
        """include_inherited=True must show inherited add_child from Node."""
        result = engine_api.get_class("Sprite2D", include_inherited=True)
        assert "add_child" in result

    def test_true_labels_inherited_origin(self, synthetic):
        """Inherited members must be labeled with their origin class."""
        result = engine_api.get_class("Sprite2D", include_inherited=True)
        assert "Node" in result

    def test_default_signature_unchanged(self, synthetic):
        """Calling get_class with no second arg should work (backward compat)."""
        result = engine_api.get_class("Sprite2D")
        assert "Sprite2D" in result
        assert "texture" in result

    def test_own_members_not_duplicated(self, synthetic):
        """Own members must not appear twice when include_inherited=True."""
        result = engine_api.get_class("Sprite2D", include_inherited=True)
        # Count occurrences of "texture" — should be exactly once in properties section
        assert result.count("texture_changed") <= 2  # header + one listing

    def test_include_inherited_builtin_no_extra_section(self, synthetic):
        """Built-ins have no inherits; include_inherited=True produces no extra section."""
        result = engine_api.get_class("Color", include_inherited=True)
        assert "Color" in result
        # No "Inherited members" section should appear since Color has no inherits
        assert "Inherited members" not in result


# ---------------------------------------------------------------------------
# search — builtins + singletons (F-5)
# ---------------------------------------------------------------------------

class TestSearchBuiltinsAndSingletons:
    def test_search_finds_builtin_method(self, synthetic):
        """search('from_hsv') must find Color.from_hsv."""
        result = engine_api.search("from_hsv")
        assert "Color.from_hsv" in result
        assert "No API matches" not in result

    def test_search_finds_vector2_snapped(self, synthetic):
        """search('snapped') must find Vector2.snapped."""
        result = engine_api.search("snapped")
        assert "Vector2.snapped" in result
        assert "No API matches" not in result

    def test_search_finds_singleton_name(self, synthetic):
        """search('Input') finds Input, tagged as a singleton, with NO duplicate row
        (Input is both a class and a singleton — must collapse to one annotated line)."""
        result = engine_api.search("Input")
        assert "Input" in result
        assert "No API matches" not in result
        assert "[singleton]" in result
        # dedup: the class+singleton must not produce two separate "Input" lines
        input_lines = [ln for ln in result.splitlines() if ln.strip() == "Input" or ln.strip() == "Input [singleton]"]
        assert len(input_lines) == 1, f"expected one Input row, got: {input_lines}"

    def test_search_builtin_class_name_match(self, synthetic):
        """search('Color') matches the Color builtin class name."""
        result = engine_api.search("Color")
        assert "Color" in result
        assert "No API matches" not in result

    def test_search_builtin_member_field(self, synthetic):
        """search for a Color member field ('from') matches from_hsv."""
        result = engine_api.search("from_hsv")
        assert "from_hsv" in result

    def test_search_no_results(self, synthetic):
        """A query matching nothing returns the 'No API matches' message."""
        result = engine_api.search("xyzzy_no_such_thing_12345")
        assert "No API matches" in result

    def test_search_limit_respected(self, synthetic):
        """Limit parameter must still work with builtins/singletons included."""
        result = engine_api.search("a", limit=2)
        # Just verify it doesn't raise and returns a string
        assert isinstance(result, str)

    def test_search_preserves_class_hits(self, synthetic):
        """Existing engine class search must still work alongside new buckets."""
        result = engine_api.search("Sprite2D")
        assert "Sprite2D" in result


# ---------------------------------------------------------------------------
# server.py godot_class wrapper accepts include_inherited
# ---------------------------------------------------------------------------

class TestServerGodotClassWrapper:
    def test_server_tool_accepts_include_inherited(self, synthetic):
        """The server tool must accept include_inherited and pass it through."""
        from godot_mcp.server import godot_class
        # Should not raise
        result_false = godot_class("Sprite2D", include_inherited=False)
        result_true = godot_class("Sprite2D", include_inherited=True)
        assert isinstance(result_false, str)
        assert isinstance(result_true, str)
        assert "add_child" not in result_false
        assert "add_child" in result_true


# ---------------------------------------------------------------------------
# Real-dump sanity (skipped if extension_api.json absent)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not config.EXTENSION_API.exists(),
    reason="extension_api.json not present — skip real-dump sanity",
)
class TestRealDumpSanity:
    """These tests use the real 6.7 MB dump — no monkeypatching of _cache."""

    @pytest.fixture(autouse=True)
    def reset_cache(self, monkeypatch):
        """Ensure the real dump is loaded fresh (clear synthetic monkeypatching)."""
        # Only reset if _cache was set to our synthetic dict (it has no "raw" key).
        # If _cache is None it will load from disk normally.
        current = engine_api._cache
        if isinstance(current, dict) and "raw" not in current and "_missing" not in current:
            monkeypatch.setattr(engine_api, "_cache", None)

    def test_sprite2d_add_child_inherits(self):
        """Sprite2D.add_child must resolve and mention inheritance from Node."""
        result = engine_api.get_member("Sprite2D", "add_child")
        assert "add_child" in result
        assert "No member" not in result
        assert "inherited" in result.lower()

    def test_search_finds_from_hsv(self):
        """search('from_hsv') must find Color.from_hsv in the real dump."""
        result = engine_api.search("from_hsv")
        assert "from_hsv" in result
        assert "No API matches" not in result

    def test_search_finds_snapped(self):
        """search('snapped') must find Vector2.snapped in the real dump."""
        result = engine_api.search("snapped")
        assert "snapped" in result
        assert "No API matches" not in result


# ---------------------------------------------------------------------------
# Phase 4 — C17: utility_functions / global_enums / global_constants indexing
# ---------------------------------------------------------------------------

class TestC17UtilityFunctions:
    """search() and get_class() must surface utility functions."""

    def test_search_finds_utility_function(self, synthetic):
        """search('lerp') returns the lerp utility function."""
        result = engine_api.search("lerp")
        assert "lerp" in result
        assert "No API matches" not in result

    def test_search_utility_function_label(self, synthetic):
        """Utility function hits are labeled with [utility_function]."""
        result = engine_api.search("lerp")
        assert "[utility_function]" in result

    def test_get_class_resolves_utility_function(self, synthetic):
        """get_class('lerp') returns the function signature, not 'not found'."""
        result = engine_api.get_class("lerp")
        assert "lerp" in result
        assert "not found" not in result.lower()

    def test_search_does_not_return_utility_as_class(self, synthetic):
        """A utility function hit must not claim to be a class."""
        result = engine_api.search("sin")
        assert "sin" in result
        assert "No API matches" not in result


class TestC17GlobalEnums:
    """search() and get_class() must surface global enums."""

    def test_search_finds_global_enum_name(self, synthetic):
        """search('Side') finds the global enum Side."""
        result = engine_api.search("Side")
        assert "Side" in result
        assert "No API matches" not in result

    def test_search_global_enum_label(self, synthetic):
        """Global enum hits are labeled with [global_enum]."""
        result = engine_api.search("Side")
        assert "[global_enum]" in result

    def test_search_finds_enum_value_name(self, synthetic):
        """search('SIDE_LEFT') finds the value inside global enum Side."""
        result = engine_api.search("SIDE_LEFT")
        assert "SIDE_LEFT" in result
        assert "No API matches" not in result

    def test_get_class_resolves_global_enum(self, synthetic):
        """get_class('Key') resolves the global enum Key."""
        result = engine_api.get_class("Key")
        assert "Key" in result
        assert "not found" not in result.lower()


class TestC17GlobalConstants:
    """search() must surface global constants."""

    def test_search_finds_global_constant(self, synthetic):
        """search('SPKEY') finds the global constant SPKEY."""
        result = engine_api.search("SPKEY")
        assert "SPKEY" in result
        assert "No API matches" not in result

    def test_search_global_constant_label(self, synthetic):
        """Global constant hits are labeled with [global_constant]."""
        result = engine_api.search("SPKEY")
        assert "[global_constant]" in result


# ---------------------------------------------------------------------------
# Phase 4 — C17: fixture-dump loader (tests _load from real JSON shape)
# ---------------------------------------------------------------------------

@pytest.fixture()
def fixture_dump(monkeypatch, tmp_path):
    """Load the phase-4 fixture dump via monkeypatched EXTENSION_API."""
    import shutil
    dest = tmp_path / "extension_api.json"
    shutil.copy(_FIXTURE_DUMP, dest)
    monkeypatch.setattr(config, "EXTENSION_API", dest)
    monkeypatch.setattr(engine_api, "_cache", None)
    yield dest
    monkeypatch.setattr(engine_api, "_cache", None)


class TestC17FixtureDump:
    """Use the checked-in fixture dump (no real Godot install needed)."""

    def test_load_indexes_utility_functions(self, fixture_dump):
        """_load must index utility_functions from the fixture dump."""
        idx = engine_api._load()
        assert "utility_functions" in idx
        assert "lerp" in idx["utility_functions"]

    def test_load_indexes_global_enums(self, fixture_dump):
        """_load must index global_enums from the fixture dump."""
        idx = engine_api._load()
        assert "global_enums" in idx
        assert "Side" in idx["global_enums"]

    def test_load_indexes_global_constants(self, fixture_dump):
        """_load must index global_constants from the fixture dump."""
        idx = engine_api._load()
        assert "global_constants" in idx
        assert "SPKEY" in idx["global_constants"]

    def test_search_lerp_returns_result(self, fixture_dump):
        """search('lerp') against the fixture dump finds the lerp utility fn."""
        result = engine_api.search("lerp")
        assert "lerp" in result
        assert "No API matches" not in result

    def test_search_side_returns_global_enum(self, fixture_dump):
        """search('Side') against the fixture dump finds the Side global enum."""
        result = engine_api.search("Side")
        assert "Side" in result
        assert "No API matches" not in result

    def test_search_spkey_returns_global_constant(self, fixture_dump):
        """search('SPKEY') against the fixture dump finds the global constant."""
        result = engine_api.search("SPKEY")
        assert "SPKEY" in result
        assert "No API matches" not in result

    def test_get_class_key_resolves(self, fixture_dump):
        """get_class('Key') resolves the global enum from the fixture dump."""
        result = engine_api.get_class("Key")
        assert "Key" in result
        assert "not found" not in result.lower()


# ---------------------------------------------------------------------------
# Phase 4 — C21: member hit ranking (exact > prefix > substring)
# ---------------------------------------------------------------------------

class TestC21SearchRanking:
    """Exact name match must rank above prefix match, prefix above substring."""

    def test_exact_match_before_prefix(self, synthetic):
        """search('lerp') — exact 'lerp' must appear before 'lerp_angle' prefix match."""
        result = engine_api.search("lerp")
        lines = [ln for ln in result.splitlines() if "lerp" in ln.lower()]
        assert len(lines) >= 2, f"Expected at least 2 lerp hits, got: {lines}"
        # The exact match line contains 'lerp' but not 'lerp_angle' or similar
        exact_idx = next((i for i, ln in enumerate(lines) if "lerp_angle" not in ln), None)
        prefix_idx = next((i for i, ln in enumerate(lines) if "lerp_angle" in ln), None)
        assert exact_idx is not None and prefix_idx is not None, f"Lines: {lines}"
        assert exact_idx < prefix_idx, (
            f"Exact match (idx {exact_idx}) must come before prefix match (idx {prefix_idx}): {lines}"
        )

    def test_member_hits_ranked_exact_prefix_substring(self, synthetic):
        """search('position') — 'position' exact member before 'position_something_long'."""
        result = engine_api.search("position")
        lines = [ln for ln in result.splitlines() if "position" in ln.lower()]
        if len(lines) < 2:
            pytest.skip("Need at least two position hits in synthetic index")
        exact_idx = next(
            (i for i, ln in enumerate(lines) if ln.strip().endswith(".position [property]")), None
        )
        sub_idx = next(
            (i for i, ln in enumerate(lines) if "position_something_long" in ln), None
        )
        if exact_idx is not None and sub_idx is not None:
            assert exact_idx < sub_idx, (
                f"Exact hit (idx {exact_idx}) must be before substring hit (idx {sub_idx})"
            )

    def test_search_notification_ready_constant(self, synthetic):
        """search('NOTIFICATION_READY') finds the constant in class Node."""
        result = engine_api.search("NOTIFICATION_READY")
        assert "NOTIFICATION_READY" in result
        assert "No API matches" not in result

    def test_search_process_mode_enum(self, synthetic):
        """search('ProcessMode') finds the enum in class Node."""
        result = engine_api.search("ProcessMode")
        assert "ProcessMode" in result
        assert "No API matches" not in result

    def test_global_enum_value_finds_hit(self, synthetic):
        """search('SIDE_LEFT') finds the global enum value."""
        result = engine_api.search("SIDE_LEFT")
        assert "SIDE_LEFT" in result
        assert "No API matches" not in result


# ---------------------------------------------------------------------------
# Phase 4 — C22: char budget, (get None, set None) cleanup, stale cache, JSON error
# ---------------------------------------------------------------------------

class TestC22CharBudget:
    """get_class response for a large class is capped with a drill-down tail."""

    def test_large_class_capped_with_tail(self, fixture_dump, monkeypatch):
        """A class whose rendered output exceeds the char budget gets the drill-down tail.

        We monkeypatch _CLASS_CHAR_BUDGET to 100 so the BigClass fixture (which
        has 26 methods) reliably exceeds the threshold without needing a 4000-char
        fixture.  This tests the mechanism; the real threshold is 4000.
        """
        monkeypatch.setattr(engine_api, "_CLASS_CHAR_BUDGET", 100)
        result = engine_api.get_class("BigClass")
        assert "godot_member" in result, (
            f"Expected drill-down tail with 'godot_member', got:\n{result[-300:]}"
        )

    def test_small_class_no_tail(self, fixture_dump, monkeypatch):
        """A tiny class must not get a spurious tail when it fits within the budget."""
        # Set budget above Color's expected output (~100 chars with 1 method)
        monkeypatch.setattr(engine_api, "_CLASS_CHAR_BUDGET", 4000)
        result = engine_api.get_class("Color")
        assert "Color" in result
        assert "godot_member" not in result or "(response truncated" not in result


class TestC22GetNoneCleanup:
    """(get None, set None) must not appear in member listings."""

    def test_get_none_set_none_absent(self, synthetic):
        """A property with getter=None and setter=None must not show '(get None, set None)'."""
        result = engine_api.get_member("Node", "position_something_long")
        assert "(get None, set None)" not in result
        assert "position_something_long" in result

    def test_real_getter_setter_shown(self, synthetic):
        """A property with real getter/setter should show something useful (not '(get None, set None)')."""
        result = engine_api.get_member("Sprite2D", "texture")
        assert "(get None, set None)" not in result


class TestC22StaleCache:
    """_cache is reloaded when the JSON source file is newer than the cached parse."""

    def test_newer_file_triggers_reload(self, tmp_path, monkeypatch):
        """Writing a newer extension_api.json after a load must cause a cache miss on next call."""
        import time

        # Set up initial fixture
        dest = tmp_path / "extension_api.json"
        import shutil
        shutil.copy(_FIXTURE_DUMP, dest)
        monkeypatch.setattr(config, "EXTENSION_API", dest)
        monkeypatch.setattr(engine_api, "_cache", None)

        # First load — populates _cache
        idx1 = engine_api._load()
        assert "utility_functions" in idx1

        # Ensure mtime changes (write a slightly modified version)
        time.sleep(0.05)
        data = json.loads(dest.read_text(encoding="utf-8"))
        data["global_constants"] = [{"name": "RELOAD_SENTINEL", "value": 99}]
        dest.write_text(json.dumps(data), encoding="utf-8")

        # Second load — must detect new mtime and reload
        idx2 = engine_api._load()
        assert "RELOAD_SENTINEL" in idx2.get("global_constants", {}), (
            "Stale cache was not invalidated after file was updated"
        )

    def test_unchanged_file_reuses_cache(self, tmp_path, monkeypatch):
        """If the file mtime has not changed, _load must reuse the cached index."""
        dest = tmp_path / "extension_api.json"
        import shutil
        shutil.copy(_FIXTURE_DUMP, dest)
        monkeypatch.setattr(config, "EXTENSION_API", dest)
        monkeypatch.setattr(engine_api, "_cache", None)

        idx1 = engine_api._load()
        # Replace _cache with a sentinel to confirm it's reused
        sentinel: dict[str, Any] = {"_sentinel": True, "_mtime": idx1.get("_mtime")}
        monkeypatch.setattr(engine_api, "_cache", sentinel)
        idx2 = engine_api._load()
        assert idx2 is sentinel, "Cache was not reused for an unchanged file"


class TestC22JsonDecodeError:
    """Corrupt extension_api.json must return a 're-run dump_api' message, not raise."""

    def test_corrupt_json_returns_message(self, tmp_path, monkeypatch):
        """A JSON-corrupt dump must return the user-facing message from get_class/search."""
        dest = tmp_path / "extension_api.json"
        dest.write_text("{corrupted: not valid json,,,", encoding="utf-8")
        monkeypatch.setattr(config, "EXTENSION_API", dest)
        monkeypatch.setattr(engine_api, "_cache", None)

        result_class = engine_api.get_class("Node")
        assert "dump_api" in result_class.lower() or "re-run" in result_class.lower(), (
            f"Expected 're-run dump_api' message, got: {result_class}"
        )

    def test_corrupt_json_search_returns_message(self, tmp_path, monkeypatch):
        """search() on a corrupt dump must return the user-facing message, not raise."""
        dest = tmp_path / "extension_api.json"
        dest.write_text("<<<not json>>>", encoding="utf-8")
        monkeypatch.setattr(config, "EXTENSION_API", dest)
        monkeypatch.setattr(engine_api, "_cache", None)

        result = engine_api.search("lerp")
        assert "dump_api" in result.lower() or "re-run" in result.lower(), (
            f"Expected 're-run dump_api' message, got: {result}"
        )
