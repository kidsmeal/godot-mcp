"""Resolution of the target Godot project, engine binary, and grounding data.

Everything is overridable by environment variable so the same server can be
pointed at any Godot project, but the defaults target Capsule Castle.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

# --- Target project ---------------------------------------------------------
DEFAULT_PROJECT = r"C:\Users\atk67\Documents\capsulecastle"
PROJECT_ROOT = Path(os.environ.get("GODOT_PROJECT", DEFAULT_PROJECT))

# --- Godot binary (on PATH via the ~/bin shim) ------------------------------
GODOT_BIN = os.environ.get("GODOT_BIN", "godot")

# --- Grounding data (the dumped extension_api.json) -------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("GODOT_MCP_DATA", str(REPO_ROOT / "data")))
EXTENSION_API = DATA_DIR / "extension_api.json"


def read_text(path: Path) -> str | None:
    """Read a UTF-8 text file, tolerating odd bytes. Returns None if unreadable."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return None
    except Exception:
        return None


def project_version() -> str:
    """The Godot feature string declared in the target project's project.godot."""
    pg = read_text(PROJECT_ROOT / "project.godot") or ""
    m = re.search(r"config/features=PackedStringArray\(([^)]*)\)", pg)
    return m.group(1).strip() if m else "unknown"
