"""Reference / usage finder (feature D).

Finds where an identifier is used across the project's .gd files, classified by kind
(definition / call / type / member / extends / reference). Comment- and string-aware
(masks them out, so it beats a naive grep) and Windows-glob-safe. Name-based, not
type-resolved: same-named members on different classes can't be distinguished.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from godot_mcp import config


def _mask(line: str) -> str:
    """Blank out string literals and drop a trailing comment, so identifier matches
    never land inside strings/comments."""
    out: list[str] = []
    q: str | None = None
    for i, c in enumerate(line):
        if q:
            out.append(" ")
            if c == q and line[i - 1] != "\\":
                q = None
            continue
        if c == "#":
            break
        if c in "\"'":
            q = c
            out.append(" ")
            continue
        out.append(c)
    return "".join(out)


def _classify(code: str, b: str) -> str | None:
    if re.search(rf"\bfunc\s+{b}\b", code):
        return "def:func"
    if re.search(rf"\bclass_name\s+{b}\b", code):
        return "def:class"
    if re.search(rf"\bsignal\s+{b}\b", code):
        return "def:signal"
    if re.search(rf"\bconst\s+{b}\b", code):
        return "def:const"
    if re.search(rf"\bextends\s+{b}\b", code):
        return "extends"
    if re.search(rf"(?<![.\w]){b}\s*\(", code) or re.search(rf"\.{b}\s*\(", code):
        return "call"
    if re.search(rf"(?:[:\[]|->)\s*{b}\b", code):
        return "type"
    if re.search(rf"\.{b}\b", code):
        return "member"
    if re.search(rf"\b{b}\b", code):
        return "ref"
    return None


def find_refs(symbol: str, kind: str = "all", limit: int = 200) -> str:
    if not re.fullmatch(r"\w+", symbol or ""):
        return "Provide a single identifier (letters, digits, underscore)."
    b = re.escape(symbol)
    want = None if kind in ("", "all") else kind
    skip = {".godot", ".git", ".import"}
    root = config.PROJECT_ROOT
    counts: dict[str, int] = {}
    results: list[str] = []
    truncated = False

    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in skip]
        for f in fn:
            if not f.endswith(".gd"):
                continue
            text = config.read_text(Path(dp) / f)
            if not text or symbol not in text:
                continue
            rel = "res://" + str((Path(dp) / f).relative_to(root)).replace("\\", "/")
            for i, raw in enumerate(text.splitlines(), start=1):
                if symbol not in raw:
                    continue
                k = _classify(_mask(raw), b)
                if not k:
                    continue
                counts[k] = counts.get(k, 0) + 1
                if want and not k.startswith(want):
                    continue
                if len(results) < limit:
                    results.append(f"{rel}:{i}  [{k}]  {raw.strip()[:120]}")
                else:
                    truncated = True

    summary = ", ".join(f"{v} {kk}" for kk, v in sorted(counts.items())) or "none found"
    body = "\n".join(results) if results else "(no matching occurrences)"
    tail = f"\n…(listing truncated at {limit})" if truncated else ""
    return (
        f"References to `{symbol}`: {summary}\n\n{body}{tail}\n\n"
        "(name-based across .gd, comment/string-aware; not type-resolved.)"
    )
