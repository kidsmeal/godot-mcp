"""C16 tests: _write_mcp_json safety.

_write_mcp_json must refuse to write (and leave the original file byte-identical)
when the existing .mcp.json is corrupt or has a non-dict top level. It must also
preserve other server registrations on a valid merge.

All tests are fully offline — no Godot binary needed.
"""
from __future__ import annotations

import json
from pathlib import Path

# Import the function under test directly; it is not exported from __init__,
# so we reach into the module.
from godot_mcp.init import _write_mcp_json

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mcp_path(tmp_path: Path) -> Path:
    return tmp_path / ".mcp.json"


def _write_existing(tmp_path: Path, content: str) -> Path:
    """Write raw bytes to .mcp.json and return the path."""
    p = _mcp_path(tmp_path)
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Corrupt JSON — must refuse and leave file untouched
# ---------------------------------------------------------------------------

class TestCorruptJson:
    def test_invalid_json_returns_error_string(self, tmp_path):
        """_write_mcp_json must return an error message string on corrupt JSON, not None."""
        _write_existing(tmp_path, "{ this is not json }")
        result = _write_mcp_json(tmp_path, "godot")
        # The function must signal refusal — return a string (not a Path)
        assert isinstance(result, str), "Expected an error string on corrupt JSON"
        assert "corrupt" in result.lower() or "parse" in result.lower() or "invalid" in result.lower() or "refused" in result.lower(), (
            f"Error string must mention the problem; got: {result!r}"
        )

    def test_invalid_json_leaves_file_byte_identical(self, tmp_path):
        """The original file must be byte-identical after a refusal (no clobber)."""
        original = "{ this is not json }"
        p = _write_existing(tmp_path, original)
        before = p.read_bytes()
        _write_mcp_json(tmp_path, "godot")
        after = p.read_bytes()
        assert before == after, "File must not be modified on a corrupt-JSON refusal"

    def test_truncated_json_leaves_file_byte_identical(self, tmp_path):
        """A truncated/incomplete JSON file must not be clobbered."""
        original = '{"mcpServers": {"other-server": {"command": "node"'
        p = _write_existing(tmp_path, original)
        before = p.read_bytes()
        _write_mcp_json(tmp_path, "godot")
        after = p.read_bytes()
        assert before == after

    def test_empty_file_leaves_file_byte_identical(self, tmp_path):
        """An empty .mcp.json (zero bytes) is also invalid JSON — must not be overwritten."""
        p = _write_existing(tmp_path, "")
        before = p.read_bytes()
        _write_mcp_json(tmp_path, "godot")
        after = p.read_bytes()
        assert before == after


# ---------------------------------------------------------------------------
# Top-level JSON array — must refuse and leave file untouched
# ---------------------------------------------------------------------------

class TestTopLevelArray:
    def test_json_array_returns_error_string(self, tmp_path):
        """A top-level JSON array is not a valid .mcp.json — must return an error string."""
        _write_existing(tmp_path, '[{"mcpServers": {}}]')
        result = _write_mcp_json(tmp_path, "godot")
        assert isinstance(result, str), "Expected an error string for top-level array"

    def test_json_array_leaves_file_byte_identical(self, tmp_path):
        """Top-level array file must not be modified."""
        original = '[{"mcpServers": {}}]'
        p = _write_existing(tmp_path, original)
        before = p.read_bytes()
        _write_mcp_json(tmp_path, "godot")
        after = p.read_bytes()
        assert before == after, "File must not be modified on a top-level-array refusal"

    def test_json_string_returns_error_string(self, tmp_path):
        """A top-level JSON string is also not a valid .mcp.json."""
        _write_existing(tmp_path, '"just a string"')
        result = _write_mcp_json(tmp_path, "godot")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Valid merge — other server entries must survive
# ---------------------------------------------------------------------------

class TestValidMerge:
    def test_other_servers_preserved(self, tmp_path):
        """Other MCP server entries in mcpServers must not be removed on merge."""
        existing = {
            "mcpServers": {
                "other-server": {"command": "node", "args": ["other.js"]},
            }
        }
        p = _write_existing(tmp_path, json.dumps(existing))
        result = _write_mcp_json(tmp_path, "godot")
        # Successful merge returns a Path
        assert isinstance(result, Path), f"Expected Path on success; got: {result!r}"
        data = json.loads(p.read_text(encoding="utf-8"))
        assert "other-server" in data["mcpServers"], "Other server must be preserved"
        assert "godot-grounding" in data["mcpServers"], "godot-grounding must be added"

    def test_new_file_created_on_absent_mcp_json(self, tmp_path):
        """.mcp.json absent → create it and return a Path."""
        result = _write_mcp_json(tmp_path, "godot")
        assert isinstance(result, Path)
        p = _mcp_path(tmp_path)
        assert p.exists()
        data = json.loads(p.read_text(encoding="utf-8"))
        assert "godot-grounding" in data["mcpServers"]

    def test_existing_godot_grounding_overwritten(self, tmp_path):
        """A stale godot-grounding entry must be replaced, not duplicated."""
        existing = {
            "mcpServers": {
                "godot-grounding": {"command": "old-python", "args": ["old.py"]},
            }
        }
        _write_existing(tmp_path, json.dumps(existing))
        _write_mcp_json(tmp_path, "godot")
        p = _mcp_path(tmp_path)
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data["mcpServers"]["godot-grounding"]["command"] != "old-python"

    def test_mcp_servers_non_dict_is_replaced_gracefully(self, tmp_path):
        """If mcpServers is not a dict (e.g. it's a list), the merge must handle it gracefully.
        Since mcpServers being non-dict is a sign of a corrupt file, the function should
        either refuse or treat it as missing — but must not raise."""
        existing = {"mcpServers": ["not", "a", "dict"]}
        _write_existing(tmp_path, json.dumps(existing))
        # Must not raise — either refuse (return str) or succeed (return Path)
        result = _write_mcp_json(tmp_path, "godot")
        assert isinstance(result, (str, Path)), f"Must return str or Path; got: {type(result)}"

    def test_top_level_extra_keys_preserved(self, tmp_path):
        """Non-mcpServers top-level keys in a valid .mcp.json must survive the merge."""
        existing = {
            "version": 2,
            "mcpServers": {},
        }
        p = _write_existing(tmp_path, json.dumps(existing))
        _write_mcp_json(tmp_path, "godot")
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data.get("version") == 2, "Top-level 'version' key must survive merge"


# ---------------------------------------------------------------------------
# Import-time crash surface (C15 cross-cutting)
# ---------------------------------------------------------------------------

class TestImportTimeSafety:
    """config.py calls profile.load() at module import time (config.py:20).
    A shape-violating toml must not raise when godot_mcp.config is imported fresh
    in a subprocess — this is the actual load path, not just profile.load() directly."""

    def test_import_with_catalog_table_does_not_raise(self, tmp_path):
        """Importing godot_mcp.config with a [catalog]-table profile must not raise."""
        import subprocess
        import sys
        (tmp_path / "project.godot").write_text('[application]\nconfig/name="T"\n', encoding="utf-8")
        (tmp_path / "godot-mcp.toml").write_text(
            "[catalog]\nname = \"items\"\nfile = \"items.gd\"\npattern = \"r\"\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, "-c", "import godot_mcp.config"],
            env={**__import__("os").environ, "GODOT_PROJECT": str(tmp_path)},
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"import raised:\n{result.stderr}"

    def test_import_with_docs_string_does_not_raise(self, tmp_path):
        """Importing godot_mcp.config with docs=\"string\" profile must not raise."""
        import subprocess
        import sys
        (tmp_path / "project.godot").write_text('[application]\nconfig/name="T"\n', encoding="utf-8")
        (tmp_path / "godot-mcp.toml").write_text(
            "[project]\nname = \"T\"\ndocs = \"not-a-table\"\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, "-c", "import godot_mcp.config"],
            env={**__import__("os").environ, "GODOT_PROJECT": str(tmp_path)},
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"import raised:\n{result.stderr}"
