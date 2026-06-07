"""Engine grounding: exact Godot API from the version-pinned extension_api.json.

extension_api.json is produced by `godot --headless --dump-extension-api` and
contains every class, method, property, signal, enum, and constant for the
*installed* engine build. Grounding against it eliminates the single biggest
failure mode of LLM Godot code: hallucinated or version-renamed API members.
"""
from __future__ import annotations

import json
from typing import Any

from godot_mcp import config, docs

_cache: dict[str, Any] | None = None


def _load() -> dict[str, Any]:
    global _cache
    if _cache is not None:
        return _cache
    if not config.EXTENSION_API.exists():
        _cache = {"_missing": True}
        return _cache
    data = json.loads(config.EXTENSION_API.read_text(encoding="utf-8"))
    classes = {c["name"]: c for c in data.get("classes", [])}
    builtins = {c["name"]: c for c in data.get("builtin_classes", [])}
    singletons = {s["name"]: s for s in data.get("singletons", [])}
    ci = {k.lower(): k for k in list(classes) + list(builtins)}
    _cache = {
        "raw": data,
        "classes": classes,
        "builtins": builtins,
        "singletons": singletons,
        "ci": ci,
    }
    return _cache


def _missing_msg() -> str:
    return (
        f"extension_api.json not found at {config.EXTENSION_API}.\n"
        "Generate it once (signatures are pinned to your installed engine):\n"
        "    godot --headless --dump-extension-api      # run inside the data/ dir\n"
        "or run scripts/dump_api.ps1 from this repo."
    )


def _pretty_type(t: str | None) -> str:
    if not t:
        return "void"
    if t.startswith("typedarray::"):
        return f"Array[{t.split('::', 1)[1]}]"
    if t.startswith(("enum::", "bitfield::")):
        return t.split("::", 1)[1]
    return t


def _trunc(s: str, n: int) -> str:
    s = s.strip()
    return s if len(s) <= n else s[:n].rstrip() + "…"


def _method_return(m: dict[str, Any]) -> str:
    rv = m.get("return_value")
    if isinstance(rv, dict):
        return _pretty_type(rv.get("type"))
    if "return_type" in m:  # builtin_classes use this key
        return _pretty_type(m.get("return_type"))
    return "void"


def _format_method(m: dict[str, Any]) -> str:
    args = []
    for a in m.get("arguments", []):
        s = f'{a["name"]}: {_pretty_type(a.get("type"))}'
        if "default_value" in a:
            s += f" = {a['default_value']}"
        args.append(s)
    if m.get("is_vararg"):
        args.append("...")
    prefix = "static " if m.get("is_static") else ""
    sig = f'{prefix}func {m["name"]}({", ".join(args)}) -> {_method_return(m)}'
    flags = [f for f, on in (("const", m.get("is_const")), ("virtual", m.get("is_virtual"))) if on]
    return sig + (f"   [{', '.join(flags)}]" if flags else "")


def _walk_inherits(
    class_name: str, classes: dict[str, Any]
) -> list[tuple[str, dict[str, Any]]]:
    """Return a list of (ancestor_name, record) walking up the inherits chain.

    Stops when a parent is not found in ``classes`` or a cycle is detected.
    The starting class itself is NOT included.
    """
    seen: set[str] = {class_name}
    result: list[tuple[str, dict[str, Any]]] = []
    current = class_name
    while True:
        rec = classes.get(current)
        if rec is None:
            break
        parent = rec.get("inherits")
        if not parent or parent in seen:
            break
        parent_rec = classes.get(parent)
        if parent_rec is None:
            break
        seen.add(parent)
        result.append((parent, parent_rec))
        current = parent
    return result


def get_class(name: str, include_inherited: bool = False) -> str:
    idx = _load()
    if idx.get("_missing"):
        return _missing_msg()
    real = idx["ci"].get(name.lower())
    if not real:
        return f'Class "{name}" not found. Try godot_search("{name}").'
    c = idx["classes"].get(real) or idx["builtins"].get(real)

    header = real + (f' : {c["inherits"]}' if c.get("inherits") else "")
    lines = [f"class {header}"]
    meta = []
    if c.get("is_refcounted"):
        meta.append("RefCounted")
    if c.get("is_instantiable"):
        meta.append("instantiable")
    if c.get("api_type"):
        meta.append(str(c["api_type"]))
    if meta:
        lines.append("  " + ", ".join(meta))

    dd = docs.class_docs(real)
    if dd and (dd["brief"] or dd["desc"]):
        lines.append("  " + _trunc(dd["brief"] or dd["desc"], 260))

    props = c.get("properties") or c.get("members") or []
    if props:
        lines.append("\nProperties:")
        for p in props:
            line = f'  {p["name"]}: {_pretty_type(p.get("type"))}'
            if dd and dd["members"].get(p["name"]):
                line += "  — " + _trunc(dd["members"][p["name"]], 90)
            lines.append(line)

    methods = c.get("methods") or []
    if methods:
        lines.append("\nMethods:")
        for m in methods:
            line = "  " + _format_method(m)
            if dd and dd["methods"].get(m["name"]):
                line += "   — " + _trunc(dd["methods"][m["name"]], 90)
            lines.append(line)

    signals = c.get("signals") or []
    if signals:
        lines.append("\nSignals:")
        for s in signals:
            a = ", ".join(f'{x["name"]}: {_pretty_type(x.get("type"))}' for x in s.get("arguments", []))
            line = f'  signal {s["name"]}({a})'
            if dd and dd["signals"].get(s["name"]):
                line += "   — " + _trunc(dd["signals"][s["name"]], 90)
            lines.append(line)

    enums = c.get("enums") or []
    if enums:
        lines.append("\nEnums:")
        for e in enums:
            lines.append(f'  {e["name"]}: ' + ", ".join(v["name"] for v in e.get("values", [])))

    consts = c.get("constants") or []
    if consts:
        lines.append("\nConstants:")
        lines.extend(f'  {k["name"]} = {k.get("value")}' for k in consts)

    if include_inherited and real in idx["classes"]:
        # Collect own member names to avoid duplicating them
        own_names: set[str] = set()
        for m in c.get("methods") or []:
            own_names.add(m["name"])
        for p in c.get("properties") or c.get("members") or []:
            own_names.add(p["name"])
        for s in c.get("signals") or []:
            own_names.add(s["name"])

        ancestors = _walk_inherits(real, idx["classes"])
        inh_lines: list[str] = []
        for origin, arec in ancestors:
            add = docs.class_docs(origin)
            for m in arec.get("methods") or []:
                if m["name"] not in own_names:
                    own_names.add(m["name"])
                    line = f'  {_format_method(m)}   [from {origin}]'
                    if add and add["methods"].get(m["name"]):
                        line += "   — " + _trunc(add["methods"][m["name"]], 80)
                    inh_lines.append(line)
            for p in arec.get("properties") or []:
                if p["name"] not in own_names:
                    own_names.add(p["name"])
                    inh_lines.append(
                        f'  {p["name"]}: {_pretty_type(p.get("type"))}   [property, from {origin}]'
                    )
            for s in arec.get("signals") or []:
                if s["name"] not in own_names:
                    own_names.add(s["name"])
                    a = ", ".join(
                        f'{x["name"]}: {_pretty_type(x.get("type"))}' for x in s.get("arguments", [])
                    )
                    inh_lines.append(f'  signal {s["name"]}({a})   [from {origin}]')

        if inh_lines:
            lines.append("\nInherited members:")
            lines.extend(inh_lines)

    return "\n".join(lines)


def _scan_record_for_member(c: dict[str, Any], ml: str) -> list[str]:
    """Scan a single class/builtin record for member ``ml`` (lowercased).

    Returns a list of formatted hit strings (empty if nothing matched).
    """
    hits: list[str] = []
    for m in c.get("methods") or []:
        if m["name"].lower() == ml:
            hits.append(_format_method(m))
    for p in c.get("properties") or c.get("members") or []:
        if p["name"].lower() == ml:
            hits.append(
                f'property {p["name"]}: {_pretty_type(p.get("type"))} '
                f'(get {p.get("getter")}, set {p.get("setter")})'
            )
    for s in c.get("signals") or []:
        if s["name"].lower() == ml:
            a = ", ".join(f'{x["name"]}: {_pretty_type(x.get("type"))}' for x in s.get("arguments", []))
            hits.append(f'signal {s["name"]}({a})')
    for e in c.get("enums") or []:
        if e["name"].lower() == ml:
            hits.append(f'enum {e["name"]}: ' + ", ".join(f'{v["name"]}={v["value"]}' for v in e.get("values", [])))
    for k in c.get("constants") or []:
        if k["name"].lower() == ml:
            hits.append(f'const {k["name"]} = {k.get("value")}')
    return hits


def get_member(class_name: str, member: str) -> str:
    idx = _load()
    if idx.get("_missing"):
        return _missing_msg()
    real = idx["ci"].get(class_name.lower())
    if not real:
        return f'Class "{class_name}" not found. Try godot_search("{class_name}").'
    c = idx["classes"].get(real) or idx["builtins"].get(real)
    ml = member.lower()

    out = _scan_record_for_member(c, ml)

    # Inherited resolution: walk the ancestor chain for engine classes only.
    # Built-ins have no inherits field — skip the walk for them.
    origin: str | None = None
    if not out and real in idx["classes"]:
        for ancestor_name, ancestor_rec in _walk_inherits(real, idx["classes"]):
            hits = _scan_record_for_member(ancestor_rec, ml)
            if hits:
                out = hits
                origin = ancestor_name
                break

    if not out:
        return f'No member "{member}" on {real}. Use godot_class("{real}") to list members.'

    label = f"{real}.{member}"
    if origin:
        label += f"  (inherited from {origin})"
    result = f"{label}:\n" + "\n".join("  " + o for o in out)

    # Fetch doc description from the origin class when inherited, else from real.
    doc_class = origin if origin else real
    dd = docs.class_docs(doc_class)
    if dd:
        for bucket in ("methods", "members", "signals", "constants"):
            desc = next((v for k, v in dd[bucket].items() if k.lower() == ml and v), "")
            if desc:
                result += "\n\n" + _trunc(desc, 700)
                break
    return result


def search(query: str, limit: int = 25) -> str:
    idx = _load()
    if idx.get("_missing"):
        return _missing_msg()
    q = query.lower()
    cls_hits: list[tuple[int, str]] = []
    member_hits: list[str] = []

    singleton_names = set(idx["singletons"])

    # Engine classes
    for name, c in idx["classes"].items():
        nl = name.lower()
        if q in nl:
            score = 0 if nl == q else (1 if nl.startswith(q) else 2)
            # Most singletons share their class name — tag the class row instead of
            # emitting a separate one (avoids a duplicate entry that eats into `limit`).
            label = f"{name} [singleton]" if name in singleton_names else name
            cls_hits.append((score, label))
        for m in c.get("methods") or []:
            if q in m["name"].lower():
                member_hits.append(f'{name}.{m["name"]}()')
        for s in c.get("signals") or []:
            if q in s["name"].lower():
                member_hits.append(f'{name}.{s["name"]} [signal]')
        for p in c.get("properties") or []:
            if q in p["name"].lower():
                member_hits.append(f'{name}.{p["name"]} [property]')

    # Built-in types (Color, Vector2, …)
    for name, c in idx["builtins"].items():
        nl = name.lower()
        if q in nl:
            score = 0 if nl == q else (1 if nl.startswith(q) else 2)
            cls_hits.append((score, name))
        for m in c.get("methods") or []:
            if q in m["name"].lower():
                member_hits.append(f'{name}.{m["name"]}()')
        for mem in c.get("members") or []:
            if q in mem["name"].lower():
                member_hits.append(f'{name}.{mem["name"]} [property]')
        for con in c.get("constants") or []:
            if q in con["name"].lower():
                member_hits.append(f'{name}.{con["name"]} [constant]')

    # Singletons whose name is NOT also a class (those are tagged on the class row
    # above). Covers the rare case of a singleton exposed under a different name.
    for sname, s in idx["singletons"].items():
        if sname in idx["classes"]:
            continue
        nl = sname.lower()
        if q in nl:
            score = 0 if nl == q else (1 if nl.startswith(q) else 2)
            label = sname if s.get("type") == sname else f'{sname} ({s.get("type")})'
            cls_hits.append((score, f'{label} [singleton]'))

    cls_hits.sort()
    results = [n for _, n in cls_hits] + member_hits
    if not results:
        return f'No API matches for "{query}".'
    shown = results[:limit]
    tail = "" if len(results) <= limit else f"\n…({len(results) - limit} more)"
    return "\n".join(shown) + tail
