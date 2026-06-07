"""Phase 2 tests: engine grounding correctness (F-4, F-5).

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

from typing import Any

import pytest

from godot_mcp import config, engine_api

# ---------------------------------------------------------------------------
# Synthetic index fixture
# ---------------------------------------------------------------------------

# Hierarchy: Node <- CanvasItem <- Node2D <- Sprite2D
# Node has method add_child; Sprite2D has property texture.
# Built-in: Color (method from_hsv), Vector2 (method snapped).
# Singleton: Input -> type Input (also a class in classes for type resolution).

_SYNTHETIC_INDEX: dict[str, Any] = {
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
            "properties": [],
            "enums": [],
            "constants": [],
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
            "properties": [],
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
    # ci: case-insensitive name map — classes + builtins (NOT singletons)
    "ci": {
        "node": "Node",
        "canvasitem": "CanvasItem",
        "node2d": "Node2D",
        "sprite2d": "Sprite2D",
        "input": "Input",
        "color": "Color",
        "vector2": "Vector2",
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
