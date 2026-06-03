"""Feature A: engine doc *descriptions*.

extension_api.json carries signatures but no prose. The official source XML
(github.com/godotengine/godot/<tag>/doc/classes/<Class>.xml) carries brief/full
descriptions per class, method, property, and signal. We fetch lazily per class at
the project's exact version tag and cache under data/godot_docs/, so repeated queries
are offline. Network failure / GODOT_MCP_DOCS=0 → signatures-only (graceful).
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
import xml.etree.ElementTree as ET

from godot_mcp import config

_RAW = "https://raw.githubusercontent.com/godotengine/godot/{tag}/doc/classes/{cls}.xml"
_CACHE = config.DATA_DIR / "godot_docs"
_tag: str | None = None
_mem: dict[str, dict | None] = {}


def _enabled() -> bool:
    return os.environ.get("GODOT_MCP_DOCS", "1") != "0"


def _version_tag() -> str:
    global _tag
    if _tag is None:
        try:
            h = json.loads(config.EXTENSION_API.read_text(encoding="utf-8")).get("header", {})
            _tag = f"{h['version_major']}.{h['version_minor']}.{h.get('version_patch', 0)}-{h.get('version_status', 'stable')}"
        except Exception:
            _tag = ""
    return _tag


def _norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", text).strip() if text else ""


def _fetch_xml(name: str) -> str | None:
    cache = _CACHE / f"{name}.xml"
    if cache.exists():
        return cache.read_text(encoding="utf-8", errors="replace")
    tag = _version_tag()
    if not tag:
        return None
    try:
        req = urllib.request.Request(_RAW.format(tag=tag, cls=name), headers={"User-Agent": "godot-grounding-mcp"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = r.read().decode("utf-8", "replace")
        _CACHE.mkdir(parents=True, exist_ok=True)
        cache.write_text(data, encoding="utf-8")
        return data
    except Exception:
        return None


def class_docs(name: str) -> dict | None:
    """{brief, desc, methods{}, members{}, signals{}, constants{}} or None."""
    if not _enabled():
        return None
    if name in _mem:
        return _mem[name]
    data = _fetch_xml(name)
    if not data:
        _mem[name] = None
        return None
    try:
        root = ET.fromstring(data)
    except Exception:
        _mem[name] = None
        return None
    d: dict = {
        "brief": _norm(root.findtext("brief_description")),
        "desc": _norm(root.findtext("description")),
        "methods": {m.get("name"): _norm(m.findtext("description")) for m in root.findall("./methods/method")},
        "members": {p.get("name"): _norm(p.findtext("description")) for p in root.findall("./members/member")},
        "signals": {s.get("name"): _norm(s.findtext("description")) for s in root.findall("./signals/signal")},
        "constants": {c.get("name"): _norm(c.findtext("description")) for c in root.findall("./constants/constant")},
    }
    _mem[name] = d
    return d
