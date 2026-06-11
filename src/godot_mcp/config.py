"""Resolution of the target Godot project, engine binary, and grounding data.

Everything is overridable by environment variable so the same server can be
pointed at any Godot project, but the defaults target Capsule Castle.
"""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from godot_mcp import profile

# --- Target project ---------------------------------------------------------
DEFAULT_PROJECT = r"C:\Users\atk67\Documents\capsulecastle"
PROJECT_ROOT = Path(os.environ.get("GODOT_PROJECT", DEFAULT_PROJECT))

# --- Per-project profile (drives all project-specific behavior) -------------
PROFILE = profile.load(PROJECT_ROOT)

# --- Godot binary (on PATH via the ~/bin shim) ------------------------------
GODOT_BIN = PROFILE.godot_bin

# --- Grounding data (the dumped extension_api.json) -------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("GODOT_MCP_DATA", str(REPO_ROOT / "data")))
EXTENSION_API = DATA_DIR / "extension_api.json"


class PathEscapeError(ValueError):
    """Raised when a requested path resolves outside the project root."""


def resolve_project_path(path: str) -> Path:
    """Resolve a res://-or-relative path to an absolute Path guaranteed to live
    under PROJECT_ROOT, raising PathEscapeError if it would escape (covers '..',
    absolute paths, and symlinks via .resolve()).

    The single containment check every file-taking tool should share — read or
    write — so escapes fail with a clean refusal instead of leaking outside paths.
    """
    rel = path[len("res://"):] if path.startswith("res://") else path
    root = PROJECT_ROOT.resolve()
    target = (PROJECT_ROOT / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError as e:
        raise PathEscapeError(path) from e
    return target


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


def resolve_godot() -> list[str]:
    """Return a command prefix that launches Godot via subprocess (no shell).

    GODOT_BIN may be an absolute .exe, or 'godot' resolved on PATH. On Windows
    'godot' resolves to the ~/bin/godot.cmd shim, which CreateProcess can't run
    directly — so we read the real .exe path out of the shim.
    """
    p = Path(GODOT_BIN)
    if p.is_absolute() and p.exists():
        return [str(p)]
    found = shutil.which(GODOT_BIN)
    if found:
        if found.lower().endswith((".cmd", ".bat")):
            shim = read_text(Path(found)) or ""
            m = re.search(r'"([^"]+\.exe)"', shim)
            if m and Path(m.group(1)).exists():
                return [m.group(1)]
            # C14: refuse the cmd /c raw-shim fallback — it relies on shell=True
            # semantics via CreateProcess, is fragile, and bypasses subprocess
            # security invariants.  Return the shim path alone so the caller
            # gets a clear FileNotFoundError rather than a silent wrong invocation.
            return [found]
        return [found]
    return [GODOT_BIN]
