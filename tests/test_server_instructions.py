"""Phase 2 (6.6) test: FastMCP `instructions=` block is delivered.

Offline — no client round-trip. Importing godot_mcp.server is safe with no
project configured (tools graceful-degrade), so this needs no tmp-project
fixture, matching how other test modules import server.py tool wrappers
directly.

Confirms the four shared-semantics items (stance rule 6) that were pulled out
of the 30 per-tool docstrings live in the server-level instructions block
instead: res:// path rules, the containment refusal shape, the
`# lint: ignore` suppression syntax, and the ground -> linted edit ->
test-to-confirm loop.
"""
from __future__ import annotations

from godot_mcp.server import mcp


def test_instructions_present():
    assert mcp.instructions
    assert isinstance(mcp.instructions, str)


def test_instructions_surfaced_on_low_level_server():
    """The client actually receives instructions via mcp._mcp_server.instructions
    at initialize — confirm the low-level server exposes the same string."""
    assert mcp._mcp_server.instructions == mcp.instructions


def test_instructions_cover_res_path_rule():
    assert "res://" in mcp.instructions


def test_instructions_cover_containment_refusal_shape():
    assert "resolves outside the project root" in mcp.instructions


def test_instructions_cover_lint_ignore_syntax():
    assert "# lint: ignore" in mcp.instructions
    assert "# lint: ignore=rule,rule" in mcp.instructions


def test_instructions_cover_ground_edit_confirm_loop():
    text = mcp.instructions.lower()
    assert "ground" in text
    assert "roll back" in text or "rolls back" in text or "rollback" in text
    assert "test" in text
