"""godot_doctor: one-call health check of the MCP setup + the active profile.

Catches the silent failure modes — missing/stale engine API dump, Godot not
resolvable, gdtoolkit absent, profile paths that don't exist.

C30 note: profile and test-scene config load once at server import time.
After editing godot-mcp.toml, restart the MCP server (reload Claude Code) to
pick up the updated profile — doctor re-reads config each call, but the cached
PROFILE module-attribute reflects the value at import time.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from godot_mcp import config


def _tag(ok: bool) -> str:
    return "OK  " if ok else "FAIL"


def _version_matches(api_ver: str, feats: str) -> bool:
    """Return True if api_ver (e.g. '4.6') is one of the version tokens in the
    project features string.

    Uses exact token matching — NOT substring containment — so '4.1' does NOT
    match '4.10' (which the old `api_ver in feats` would incorrectly accept).
    """
    # Extract all quoted tokens from the PackedStringArray features string
    # e.g. '"4.6", "Forward Plus"' → ["4.6", "Forward Plus"]
    tokens = re.findall(r'"([^"]+)"', feats)
    if not tokens:
        # Fallback: split on comma and strip whitespace
        tokens = [t.strip().strip('"') for t in feats.split(",")]
    return api_ver in tokens


def report() -> str:
    lines: list[str] = []
    issues = 0

    def add(ok: bool, label: str, detail: str = "") -> None:
        nonlocal issues
        if not ok:
            issues += 1
        lines.append(f"  [{_tag(ok)}] {label}" + (f" — {detail}" if detail else ""))

    root = config.PROJECT_ROOT
    add((root / "project.godot").exists(), "project root", str(root))

    cmd = config.resolve_godot()
    g0 = cmd[0]
    godot_ok = (Path(g0).is_absolute() and Path(g0).exists()) or bool(shutil.which(g0))
    add(godot_ok, "godot binary", " ".join(cmd) if godot_ok else f"not resolvable ({g0}); set GODOT_BIN")

    # C17-doctor: check that the validation harness exists in DATA_DIR
    harness = config.DATA_DIR / "validate_script.gd"
    add(harness.exists(), "validate harness", str(harness) if harness.exists() else f"missing at {harness} — re-run setup.ps1")

    feats = config.project_version()
    api = config.EXTENSION_API
    if api.exists():
        try:
            h = json.loads(api.read_text(encoding="utf-8")).get("header", {})
            api_ver = f"{h.get('version_major')}.{h.get('version_minor')}"
            add(True, "engine API dump", h.get("version_full_name", api_ver))
            # C17-doctor: use proper token comparison, not substring match
            add(_version_matches(api_ver, feats), "API matches project version", f"API {api_ver} vs project features {feats}")
        except Exception:
            add(False, "engine API dump", f"unreadable {api}")
    else:
        add(False, "engine API dump", "missing — run setup.ps1 (or scripts/dump_api.ps1)")

    try:
        import gdtoolkit  # noqa: F401

        add(True, "gdtoolkit (linter AST backend)")
    except Exception:
        add(False, "gdtoolkit", "not installed — linter falls back to regex")

    prof = config.PROFILE
    add(True, f"profile: {prof.name}", f"{len(prof.catalogs)} catalogs, {len(prof.docs)} docs")
    for err in prof.errors:
        add(False, "profile error", err)

    for label, scene in (("unit", prof.suite_scene), ("integration", prof.integration_scene)):
        if scene:
            rel = scene[len("res://"):] if scene.startswith("res://") else scene
            add((root / rel).exists(), f"test scene ({label})", scene)

    docs_dict = prof.docs if isinstance(prof.docs, dict) else {}
    missing_docs = [v for v in docs_dict.values() if not (root / v).exists()]
    add(not missing_docs, "profile docs exist", "missing " + ", ".join(missing_docs) if missing_docs else f"{len(docs_dict)} present")

    missing_cat = [c["file"] for c in prof.catalogs if isinstance(c, dict) and c.get("file") and not (root / c["file"]).exists()]
    add(not missing_cat, "profile catalog files exist", "missing " + ", ".join(missing_cat) if missing_cat else "all present")

    try:
        from godot_mcp import bridge as _bridge  # lazy import to avoid circular dep
        ping_result = _bridge.ping()
        if ping_result.startswith("Editor bridge OK"):
            lines.append(f"  [OK  ] bridge (optional) — {ping_result}")
        else:
            lines.append(f"  [FAIL] bridge (optional) — {ping_result}")
    except Exception:  # noqa: BLE001
        lines.append("  [FAIL] bridge (optional) — could not check bridge version")

    head = f"godot_doctor — {prof.name}\n{'All good.' if issues == 0 else f'{issues} issue(s) found.'}\n"
    return head + "\n".join(lines)
