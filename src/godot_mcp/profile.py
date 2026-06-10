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
        if not isinstance(spec, dict):
            errors.append(f"catalog[{i}] is not a table (got {type(spec).__name__})")
            continue
        missing = required_catalog_keys - spec.keys()
        if missing:
            label = spec.get("name") or f"index {i}"
            errors.append(
                f"catalog[{i}] ({label!r}) missing required key(s): {', '.join(sorted(missing))}"
            )
    required_ref_keys = {"use_pattern", "valid_pattern"}
    for i, ref in enumerate(catalog_refs):
        if not isinstance(ref, dict):
            errors.append(f"lint_catalog_ref[{i}] is not a table (got {type(ref).__name__})")
            continue
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

    raw_proj = data.get("project", {})
    raw_eng = data.get("engine", {})
    raw_tests = data.get("tests", {})
    proj = raw_proj if isinstance(raw_proj, dict) else {}
    eng = raw_eng if isinstance(raw_eng, dict) else {}
    tests = raw_tests if isinstance(raw_tests, dict) else {}
    if not isinstance(raw_proj, dict) and raw_proj is not None:
        errors.append(f"[project] must be a table, got {type(raw_proj).__name__}; using defaults")
    if not isinstance(raw_eng, dict) and raw_eng is not None:
        errors.append(f"[engine] must be a table, got {type(raw_eng).__name__}; using defaults")
    if not isinstance(raw_tests, dict) and raw_tests is not None:
        errors.append(f"[tests] must be a table, got {type(raw_tests).__name__}; using defaults")

    raw_docs = data.get("docs")
    if raw_docs is None:
        docs: dict[str, str] = {k: v for k, v in _DEFAULT_DOCS.items() if (project_root / v).exists()}
    elif isinstance(raw_docs, dict):
        docs = raw_docs
    else:
        errors.append(f"[docs] must be a table, got {type(raw_docs).__name__}; using defaults")
        docs = {k: v for k, v in _DEFAULT_DOCS.items() if (project_root / v).exists()}

    raw_catalogs = data.get("catalog", [])
    raw_catalog_refs = data.get("lint_catalog_ref", [])
    catalogs: list[dict]
    catalog_refs: list[dict]
    if isinstance(raw_catalogs, list):
        catalogs = raw_catalogs
    else:
        errors.append(f"'catalog' must be an array of tables ([[catalog]]), got {type(raw_catalogs).__name__}; ignoring")
        catalogs = []
    if isinstance(raw_catalog_refs, list):
        catalog_refs = raw_catalog_refs
    else:
        errors.append(f"'lint_catalog_ref' must be an array of tables ([[lint_catalog_ref]]), got {type(raw_catalog_refs).__name__}; ignoring")
        catalog_refs = []
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
