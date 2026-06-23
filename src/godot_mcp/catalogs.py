"""Project catalogs — generic, driven by the profile's [[catalog]] specs.

Each catalog is {name, file, pattern}: a 1-group regex yields a key list, a 2-group
regex yields "key - value" pairs. `autoloads` is built in (every Godot project has
project.godot). valid_keys()/build_catalog_refs() feed the linter's typo check.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from godot_mcp import config


def _read(rel: str) -> str:
    return config.read_text(config.PROJECT_ROOT / rel) or ""


def autoloads() -> list[tuple[str, str]]:
    m = re.search(r"\[autoload\](.*?)(?:\n\[|\Z)", _read("project.godot"), re.S)
    return re.findall(r'^([A-Za-z0-9_]+)="(\*?res://[^"]+)"', m.group(1), re.M) if m else []


def _specs() -> dict[str, dict]:
    # Skip entries missing 'name' so a KeyError never escapes here; doctor surfaces them.
    return {c["name"].lower(): c for c in config.PROFILE.catalogs if c.get("name")}


def _parse(spec: dict):
    pattern = spec.get("pattern", "")
    file_rel = spec.get("file", "")
    if not pattern or not file_rel:
        return []  # incomplete spec — skip rather than crash; doctor surfaces the error
    try:
        return re.findall(pattern, _read(file_rel))
    except re.error:
        return []  # malformed profile pattern — surface as empty rather than crash


def _format(name: str, matches) -> str:
    rows = []
    for m in matches:
        rows.append("  " + ("  -  ".join(x for x in m if x) if isinstance(m, tuple) else m))
    return f"{name} ({len(matches)}):\n" + "\n".join(rows)


def catalog(kind: str = "all") -> str:
    kind = kind.lower().strip()
    specs = _specs()
    if kind in ("autoloads", "singletons"):
        a = autoloads()
        return f"autoloads ({len(a)}):\n" + "\n".join(f"  {k} -> {v}" for k, v in a)
    if kind == "all":
        # Only iterate entries that have a name; nameless entries are surfaced by doctor.
        parts = [catalog(c["name"]) for c in config.PROFILE.catalogs if c.get("name")]
        parts.append(catalog("autoloads"))
        return "\n\n".join(parts)
    if kind in specs:
        display_name = specs[kind].get("name", kind)
        return _format(display_name, _parse(specs[kind]))
    avail = ", ".join([c["name"] for c in config.PROFILE.catalogs if c.get("name")] + ["autoloads"])
    return f'Unknown catalog "{kind}". Available: {avail}'


_valid_cache: dict[str, tuple] = {}  # pattern -> (gd_signature, result_set)


def _gd_signature() -> frozenset:
    """Fingerprint of the project's .gd files as a frozenset of (relpath, mtime) pairs.

    Delegates to config.gd_signature() — the single shared implementation (C23).
    Detects renames that preserve file count and mtime-sum.
    """
    return config.gd_signature()


def valid_keys(valid_pattern: str) -> set[str]:
    """Project-wide set of keys matching a 1-group registration pattern (every .gd),
    cached against the .gd file signature."""
    try:
        rx = re.compile(valid_pattern)
    except re.error:
        return set()
    sig = _gd_signature()
    cached = _valid_cache.get(valid_pattern)
    if cached and cached[0] == sig:
        return cached[1]
    out: set[str] = set()
    for dp, dn, fn in os.walk(config.PROJECT_ROOT):
        dn[:] = [d for d in dn if d not in config._GD_SKIP_DIRS]
        for f in fn:
            if f.endswith(".gd"):
                out.update(rx.findall(config.read_text(Path(dp) / f) or ""))
    _valid_cache[valid_pattern] = (sig, out)
    return out


def build_catalog_refs() -> list[dict]:
    """Resolve the profile's lint_catalog_ref specs into {use_pattern, valid_pattern, valid_set}.

    Entries missing required keys are skipped rather than raising KeyError;
    doctor.report() surfaces those errors via Profile.errors.
    """
    out = []
    for ref in config.PROFILE.catalog_refs:
        use_pat = ref.get("use_pattern", "")
        valid_pat = ref.get("valid_pattern", "")
        if not use_pat or not valid_pat:
            continue  # incomplete spec — skip; doctor surfaces it
        out.append({"use_pattern": use_pat, "valid_pattern": valid_pat, "valid_set": valid_keys(valid_pat)})
    return out
