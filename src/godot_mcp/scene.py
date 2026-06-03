"""Feature B: scene (.tscn) grounding + linting.

.tscn is an INI-like text format: a header, [ext_resource]/[sub_resource] blocks,
[node] blocks (name/type/parent/instance + property lines), and [connection] blocks.
describe() reconstructs the node tree + dependencies so an agent can ground a scene
edit without opening the editor; lint_scene() catches the silent breakage (missing
ext_resource paths, .godot/imported refs, type-as-name nodes).
"""
from __future__ import annotations

import re
from pathlib import Path

from godot_mcp import config

_SECTION = re.compile(r"^\[(\w+)(.*)\]\s*$")
_ATTR = re.compile(r'(\w+)\s*=\s*("(?:[^"\\]|\\.)*"|[^\s\]]+)')
_PROP = re.compile(r"^([A-Za-z_]\w*)\s*=\s*(.+)$")
_EXTREF = re.compile(r'ExtResource\("([^"]+)"\)')


def _abs(res_path: str) -> Path:
    rel = res_path[len("res://"):] if res_path.startswith("res://") else res_path
    return config.PROJECT_ROOT / rel


def _unq(v: str) -> str:
    return v[1:-1] if len(v) >= 2 and v[0] == '"' and v[-1] == '"' else v


def _attrs(s: str) -> dict:
    return {k: _unq(v) for k, v in _ATTR.findall(s)}


def _sections(text: str) -> list[dict]:
    out: list[dict] = []
    cur: dict | None = None
    for raw in text.splitlines():
        m = _SECTION.match(raw)
        if m:
            cur = {"kind": m.group(1), "attrs": _attrs(m.group(2)), "props": {}}
            out.append(cur)
        elif cur is not None:
            pm = _PROP.match(raw)
            if pm:
                cur["props"].setdefault(pm.group(1), pm.group(2).strip())
    return out


def _depth(parent: str | None) -> int:
    if parent is None:
        return 0
    if parent == ".":
        return 1
    return parent.count("/") + 2


def describe(scene_path: str) -> str:
    text = config.read_text(_abs(scene_path))
    if text is None:
        return f"Not found: {scene_path}"
    if not scene_path.endswith(".tscn"):
        return "Provide a .tscn path."
    secs = _sections(text)
    ext = [s for s in secs if s["kind"] == "ext_resource"]
    sub = [s for s in secs if s["kind"] == "sub_resource"]
    nodes = [s for s in secs if s["kind"] == "node"]
    conns = [s for s in secs if s["kind"] == "connection"]
    header = next((s["attrs"] for s in secs if s["kind"] == "gd_scene"), {})
    ext_path = {s["attrs"].get("id"): s["attrs"].get("path") for s in ext}

    lines = [f"Scene: {scene_path}", f"  format {header.get('format', '?')}, uid {header.get('uid', '(none)')}"]

    if ext:
        lines.append(f"\next_resources ({len(ext)}):")
        for s in ext:
            a = s["attrs"]
            lines.append(f"  {a.get('type', '?')}  {a.get('path', '?')}  (id {a.get('id', '?')})")
    if sub:
        lines.append(f"\nsub_resources ({len(sub)}):")
        for s in sub:
            lines.append(f"  {s['attrs'].get('type', '?')}  (id {s['attrs'].get('id', '?')})")

    if nodes:
        lines.append("\nNode tree:")
        for s in nodes:
            a = s["attrs"]
            indent = "  " * (_depth(a.get("parent")) + 1)
            inst = _EXTREF.search(a.get("instance", "") or s["props"].get("instance", ""))
            kind = a.get("type") or (f"instance: {ext_path.get(inst.group(1), inst.group(1))}" if inst else "?")
            script = ""
            sref = _EXTREF.search(s["props"].get("script", ""))
            if sref:
                script = f"  (script: {ext_path.get(sref.group(1), sref.group(1))})"
            lines.append(f"{indent}{a.get('name', '?')} [{kind}]{script}")

    if conns:
        lines.append(f"\nconnections ({len(conns)}):")
        for s in conns:
            a = s["attrs"]
            lines.append(f"  [{a.get('signal', '?')}] {a.get('from', '?')} -> {a.get('to', '?')}.{a.get('method', '?')}")

    return "\n".join(lines)


def lint_scene(scene_path: str) -> list[dict]:
    text = config.read_text(_abs(scene_path))
    if text is None:
        return [{"line": 0, "severity": "error", "rule": "not-found", "message": f"{scene_path} not found"}]
    out: list[dict] = []
    root = config.PROJECT_ROOT
    for i, line in enumerate(text.splitlines(), start=1):
        if ".godot/imported" in line:
            out.append({"line": i, "severity": "error", "rule": "path-imported", "message": "references .godot/imported/ — use the source res:// path"})
        m = _SECTION.match(line)
        if not m:
            continue
        if m.group(1) == "ext_resource":
            a = _attrs(m.group(2))
            p = a.get("path", "")
            if p.startswith("res://") and not (root / p[len("res://"):]).exists():
                out.append({"line": i, "severity": "error", "rule": "missing-ext-resource", "message": f"ext_resource path does not exist: {p}"})
        elif m.group(1) == "node":
            a = _attrs(m.group(2))
            name, typ = a.get("name"), a.get("type")
            if name and typ and name == typ:
                out.append({"line": i, "severity": "info", "rule": "type-as-name", "message": f"node named '{name}' is just its type — name it by purpose"})
    return out
