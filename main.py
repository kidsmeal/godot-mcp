"""Entry point for the godot-grounding MCP server.

Adds src/ to the path so `godot_mcp` imports resolve, then runs the stdio server.
Register this file as the MCP command (see .mcp.json.example).
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "src"))

from godot_mcp.server import main  # noqa: E402

if __name__ == "__main__":
    main()
