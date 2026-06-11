"""Feature A: engine doc *descriptions*.

extension_api.json carries signatures but no prose. The official source XML
(github.com/godotengine/godot/<tag>/doc/classes/<Class>.xml) carries brief/full
descriptions per class, method, property, and signal. We fetch lazily per class at
the project's exact version tag and cache under data/godot_docs/<tag>/, so repeated
queries are offline. Network failure / GODOT_MCP_DOCS=0 → signatures-only (graceful).
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from godot_mcp import config

_RAW = "https://raw.githubusercontent.com/godotengine/godot/{tag}/doc/classes/{cls}.xml"
_CACHE = config.DATA_DIR / "godot_docs"
_tag: str | None = None
_mem: dict[str, dict | None] = {}
# Process-wide latch: set on the first connection failure (not a 404).
# A 404 just means that class page doesn't exist; a connection error means the
# network is unavailable for the whole session.
_network_down: bool = False


def _enabled() -> bool:
    return os.environ.get("GODOT_MCP_DOCS", "1") != "0"


def _version_tag() -> str:
    global _tag
    if _tag is None:
        try:
            h = json.loads(config.EXTENSION_API.read_text(encoding="utf-8")).get("header", {})
            major = h["version_major"]
            minor = h["version_minor"]
            patch = h.get("version_patch", 0)
            status = h.get("version_status", "stable")
            # Godot's official release tag omits the .0 patch component (e.g. 4.2-stable,
            # not 4.2.0-stable). A non-zero patch is always included (e.g. 4.2.1-stable).
            if patch == 0:
                _tag = f"{major}.{minor}-{status}"
            else:
                _tag = f"{major}.{minor}.{patch}-{status}"
        except Exception:
            _tag = ""
    return _tag


_BBCODE_URL = re.compile(r"\[url=[^\]]*\]([^\[]*)\[/url\]")
_BBCODE_REF = re.compile(
    r"\[(?:method|member|signal|constant|enum|param|theme_item|annotation|constructor|operator)"
    r"\s+([^\]]+)\]"
)
_BBCODE_DROP = {
    "b", "/b", "i", "/i", "u", "/u", "s", "/s", "code", "/code",
    "codeblock", "/codeblock", "codeblocks", "/codeblocks", "gdscript", "/gdscript",
    "csharp", "/csharp", "kbd", "/kbd", "center", "/center", "color", "/color",
}
_BBCODE_TAG = re.compile(r"\[([^\[\]]+)\]")
_BBCODE_IDENT = re.compile(r"^@?[A-Za-z_]\w*(?:\.\w+)*$")  # [Vector2], [Node.method], [@GlobalScope]


def _strip_bbcode(text: str) -> str:
    """Convert Godot doc BBCode to plain text for the agent: keep link text and
    reference names (`[method foo]` -> `foo`, `[Vector2]` -> `Vector2`), drop
    formatting tags (`[b]`, `[code]`, code-block language tags), `[br]` -> space.
    Leaves bracketed prose that ISN'T BBCode untouched (e.g. a numeric interval
    `[0.0, 1.0]` or an array literal), so only real markup is removed."""
    text = _BBCODE_URL.sub(r"\1", text)
    text = _BBCODE_REF.sub(r"\1", text)

    def _repl(m: "re.Match[str]") -> str:
        inner = m.group(1).strip()
        low = inner.lower()
        if low == "br":
            return " "
        if low in _BBCODE_DROP:
            return ""
        if _BBCODE_IDENT.match(inner):  # bare type/identifier reference -> keep the name
            return inner
        return m.group(0)  # not a tag we recognize -> leave as-is

    return _BBCODE_TAG.sub(_repl, text)


def _norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", _strip_bbcode(text)).strip() if text else ""


def _fetch_xml(name: str) -> str | None:
    global _network_down

    tag = _version_tag()
    if not tag:
        return None

    # Version-keyed cache directory: godot_docs/<tag>/<ClassName>.xml
    tag_dir = _CACHE / tag
    cache = tag_dir / f"{name}.xml"

    if cache.exists():
        return cache.read_text(encoding="utf-8", errors="replace")

    # Network-down latch: if a prior call failed with a connection error, skip fetch.
    if _network_down:
        return None

    url = _RAW.format(tag=tag, cls=name)
    req = urllib.request.Request(url, headers={"User-Agent": "godot-grounding-mcp"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            data = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        # An HTTP 404 means the class page doesn't exist for this version;
        # it is NOT a connectivity failure, so the latch stays clear.
        if exc.code == 404:
            return None
        # Any other HTTP error is treated as a connection problem.
        _network_down = True
        return None
    except Exception:
        # socket.error, urllib.error.URLError (non-HTTP), timeout, etc.
        _network_down = True
        return None

    # Validate XML before writing — don't cache broken data.
    try:
        ET.fromstring(data)
    except ET.ParseError:
        return None

    # Atomic write: write to a temp file in the same directory, then rename.
    # A crash mid-write leaves no partial .xml in the cache.
    tag_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = None
    try:
        fd, tmp_str = tempfile.mkstemp(
            suffix=".xml.tmp", prefix=f"{name}_", dir=tag_dir
        )
        tmp_path = Path(tmp_str)  # mkstemp returns the full absolute path
        # Close the raw fd first; write_text opens its own handle.
        os.close(fd)
        tmp_path.write_text(data, encoding="utf-8")
        os.replace(str(tmp_path), str(cache))
        tmp_path = None  # ownership transferred to cache path
    except Exception:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        return None

    return data


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
