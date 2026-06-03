#!/usr/bin/env bash
# One-liner installer for the godot-grounding MCP (macOS / Linux).
#
#   curl -fsSL https://raw.githubusercontent.com/kidsmeal/godot-mcp/main/install.sh | bash
#
# Onboard a project in the same step:
#   GODOT_MCP_PROJECT=/path/to/game  curl -fsSL <same-url> | bash
#
# Env: GODOT_MCP_DIR (install location, default ~/godot-mcp), GODOT_BIN, FORCE=1 (re-dump API).
set -euo pipefail

REPO="https://github.com/kidsmeal/godot-mcp.git"
DIR="${GODOT_MCP_DIR:-$HOME/godot-mcp}"

if [ -d "$DIR/.git" ]; then
  echo "Updating existing clone at $DIR..."
  git -C "$DIR" pull --ff-only
else
  echo "Cloning godot-mcp into $DIR..."
  git clone --depth 1 "$REPO" "$DIR"
fi
cd "$DIR"

PY="$DIR/.venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi
if ! "$PY" -c "import mcp, gdtoolkit" 2>/dev/null; then
  echo "Installing dependencies (mcp + gdtoolkit)..."
  "$PY" -m pip install -q --upgrade pip -r requirements.txt
fi

# locate Godot
GODOT="${GODOT_BIN:-}"
if [ -z "$GODOT" ]; then
  if command -v godot >/dev/null 2>&1; then
    GODOT="$(command -v godot)"
  elif [ -x "/Applications/Godot.app/Contents/MacOS/Godot" ]; then
    GODOT="/Applications/Godot.app/Contents/MacOS/Godot"
  fi
fi
if [ -z "$GODOT" ]; then
  echo "WARNING: Godot not found. Install it or set GODOT_BIN, then re-run for the engine-API dump."
else
  echo "Godot: $GODOT"
  if [ ! -f data/extension_api.json ] || [ "${FORCE:-}" = "1" ]; then
    echo "Dumping extension_api.json..."
    mkdir -p data
    ( cd data && "$GODOT" --headless --dump-extension-api )
  fi
fi

if [ -n "${GODOT_MCP_PROJECT:-}" ]; then
  echo "Onboarding project: $GODOT_MCP_PROJECT"
  PYTHONPATH="$DIR/src" "$PY" -m godot_mcp.init "$GODOT_MCP_PROJECT"
fi

echo ""
echo "Done. Reconnect the MCP server in your project, then use /godot."
echo "Onboard another project:  PYTHONPATH=$DIR/src $PY -m godot_mcp.init <project>"
echo "Uninstall from a project: PYTHONPATH=$DIR/src $PY -m godot_mcp.init --uninstall <project>"
