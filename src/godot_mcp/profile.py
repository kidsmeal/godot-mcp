"""Per-project profile — everything project-specific lives in a `godot-mcp.toml`
at the target project root (or GODOT_MCP_PROFILE). Absent → sensible Godot defaults,
so the server still works unconfigured. This is what makes the connector reusable
across Godot projects instead of hardwired to one.
"""
from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# Docs auto-exposed when no profile lists them (only those that exist are kept).
_DEFAULT_DOCS = {"AGENTS": "AGENTS.md", "CLAUDE": "CLAUDE.md", "README": "README.md", "INDEX": "docs/INDEX.md"}


@dataclass
class Profile:
    name: str = "Godot project"
    godot_bin: str = "godot"
    suite_scene: str | None = None
    integration_scene: str | None = None
    docs: dict[str, str] = field(default_factory=dict)
    catalogs: list[dict] = field(default_factory=list)       # [{name, file, pattern}]
    catalog_refs: list[dict] = field(default_factory=list)   # [{use_pattern, valid_pattern}]
    index_doc: str = "INDEX"
    test_framework: str = "custom"                           # custom | gut | gdunit4
    errors: list[str] = field(default_factory=list)          # parse/schema errors from load()


def _project_name(project_root: Path) -> str:
    try:
        pg = (project_root / "project.godot").read_text(encoding="utf-8", errors="replace")
        m = re.search(r'config/name="([^"]*)"', pg)
        return m.group(1) if m and m.group(1) else "Godot project"
    except Exception:
        return "Godot project"


def _exists(project_root: Path, rel: str | None) -> str | None:
    if not rel:
        return None
    target = rel[len("res://"):] if rel.startswith("res://") else rel
    return rel if (project_root / target).exists() else None


def _validate_catalog_specs(catalogs: list[dict], catalog_refs: list[dict]) -> list[str]:
    """Return a list of human-readable error strings for any spec missing required keys.

    Invalid specs are kept in the Profile so doctor can surface them; callers
    (catalogs.py) must guard with .get() to avoid KeyError on incomplete entries.
    """
    errors: list[str] = []
    required_catalog_keys = {"name", "file", "pattern"}
    for i, spec in enumerate(catalogs):
        missing = required_catalog_keys - spec.keys()
        if missing:
            label = spec.get("name") or f"index {i}"
            errors.append(
                f"catalog[{i}] ({label!r}) missing required key(s): {', '.join(sorted(missing))}"
            )
    required_ref_keys = {"use_pattern", "valid_pattern"}
    for i, ref in enumerate(catalog_refs):
        missing = required_ref_keys - ref.keys()
        if missing:
            errors.append(
                f"lint_catalog_ref[{i}] missing required key(s): {', '.join(sorted(missing))}"
            )
    return errors


def load(project_root: Path) -> Profile:
    path = Path(os.environ.get("GODOT_MCP_PROFILE", str(project_root / "godot-mcp.toml")))
    data: dict = {}
    errors: list[str] = []
    if path.exists():
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            # File is present but unparseable — record the error and fall back to safe defaults.
            errors.append(f"TOML parse error in {path.name}: {exc}")
            data = {}

    proj, eng, tests = data.get("project", {}), data.get("engine", {}), data.get("tests", {})
    docs = data.get("docs")
    if docs is None:
        docs = {k: v for k, v in _DEFAULT_DOCS.items() if (project_root / v).exists()}

    catalogs = data.get("catalog", [])
    catalog_refs = data.get("lint_catalog_ref", [])
    errors.extend(_validate_catalog_specs(catalogs, catalog_refs))

    return Profile(
        name=proj.get("name") or _project_name(project_root),
        godot_bin=os.environ.get("GODOT_BIN") or eng.get("godot_bin", "godot"),
        suite_scene=tests.get("suite") or _exists(project_root, "res://tests/run_all.tscn"),
        integration_scene=tests.get("integration") or _exists(project_root, "res://tests/run_integration.tscn"),
        docs=docs,
        catalogs=catalogs,
        catalog_refs=catalog_refs,
        index_doc=(proj.get("index_doc") or "INDEX"),
        test_framework=tests.get("framework", "custom"),
        errors=errors,
    )
