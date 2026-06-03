"""Project grounding: the target project's own conventions, codebase map, and
a reliable file lister (the thing generic Godot MCPs can't do).

This is what makes the connector *yours*: it serves AGENTS.md rules, the
INDEX codebase map, and a Windows-glob-safe file search keyed to res:// paths.
"""
from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

from godot_mcp import config

_HEADING = re.compile(r"^#{1,6}\s")
_TOP_HEADING = re.compile(r"^#{1,3}\s")


def _sections(text: str) -> list[tuple[str, str]]:
    """Split markdown into (heading, body) pairs."""
    sections: list[tuple[str, str]] = []
    head, body = "(intro)", []
    for ln in text.splitlines():
        if _HEADING.match(ln):
            sections.append((head, "\n".join(body)))
            head, body = ln.strip(), []
        else:
            body.append(ln)
    sections.append((head, "\n".join(body)))
    return sections


def list_docs() -> str:
    out: list[str] = []
    for name, rel in config.PROFILE.docs.items():
        text = config.read_text(config.PROJECT_ROOT / rel)
        if text is None:
            continue
        heads = [l.strip() for l in text.splitlines() if _TOP_HEADING.match(l)]
        out.append(f"## {name}  ({rel})")
        out.extend(f"  {h}" for h in heads[:60])
    return "\n".join(out) if out else "No known convention docs found under the project root."


def convention(topic: str = "") -> str:
    topic = topic.strip()
    if not topic:
        return (
            "Convention/design docs available. Call project_convention('<topic>') "
            "to pull matching sections.\n\n" + list_docs()
        )
    ql = topic.lower()
    hits: list[str] = []
    for name, rel in config.PROFILE.docs.items():
        text = config.read_text(config.PROJECT_ROOT / rel)
        if not text:
            continue
        for head, body in _sections(text):
            if ql in head.lower() or ql in body.lower():
                snippet = (head + "\n" + body).strip()
                if len(snippet) > 1800:
                    snippet = snippet[:1800] + "\n…(truncated)"
                hits.append(f"### [{name}] {head}\n{snippet}")
    if not hits:
        return f'No sections matching "{topic}". Call project_convention() to list docs.'
    return "\n\n---\n\n".join(hits[:8])


def index() -> str:
    rel = config.PROFILE.docs.get(config.PROFILE.index_doc)
    if not rel:
        return f"No index doc configured (profile index_doc={config.PROFILE.index_doc!r}). Available docs: {', '.join(config.PROFILE.docs) or 'none'}."
    return config.read_text(config.PROJECT_ROOT / rel) or f"{rel} not found."


def find_files(subdir: str = ".", pattern: str = "*", limit: int = 500) -> str:
    """Reliable recursive listing under the project root, returning res:// paths.

    Replaces Windows glob (documented to silently miss files in this project).
    """
    root = config.PROJECT_ROOT.resolve()
    try:
        base = config.resolve_project_path(subdir)
    except config.PathEscapeError:
        return f"Refused: {subdir} resolves outside the project root."
    if not base.exists():
        return f"Path not found: {subdir}"
    skip = {".godot", ".git", ".import", "__pycache__"}
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in skip]
        for fn in filenames:
            if fnmatch.fnmatch(fn, pattern):
                full = Path(dirpath) / fn
                try:
                    rel = full.resolve().relative_to(root)
                    out.append("res://" + str(rel).replace("\\", "/"))
                except ValueError:
                    continue  # symlinked outside the root — skip rather than leak an absolute path
                if len(out) >= limit:
                    return "\n".join(out) + f"\n…(truncated at {limit}; narrow with subdir/pattern)"
    return "\n".join(out) if out else f'No files matching "{pattern}" under {subdir}'
