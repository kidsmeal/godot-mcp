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

# Character budget for get_class responses. When the rendered string exceeds
# this many characters a drill-down tail is appended so the agent knows to
# call godot_member for details rather than working from a truncated view.
_CLASS_CHAR_BUDGET = 4000


def _load() -> dict[str, Any]:
    global _cache

    # Fast path: cache was set externally (monkeypatched in tests) or already
    # holds a terminal sentinel (_missing / _corrupt). Return it immediately
    # without any mtime check, so test fixtures are never clobbered.
    if _cache is not None:
        if "_missing" in _cache or "_corrupt" in _cache:
            return _cache
        # A file-loaded cache carries _mtime; a monkeypatched test cache does not.
        # Only do the staleness check when the cache came from a file load.
        if "_mtime" not in _cache:
            return _cache

    if not config.EXTENSION_API.exists():
        # File absent — return the missing sentinel (no mtime to track)
        _cache = {"_missing": True}
        return _cache

    try:
        file_mtime = config.EXTENSION_API.stat().st_mtime
    except OSError:
        _cache = {"_missing": True}
        return _cache

    # C22: reload-on-redump — reuse the cache only when the file mtime matches.
    if _cache is not None and _cache.get("_mtime") == file_mtime:
        return _cache

    try:
        data = json.loads(config.EXTENSION_API.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        _cache = {"_corrupt": True}
        return _cache

    classes = {c["name"]: c for c in data.get("classes", [])}
    builtins = {c["name"]: c for c in data.get("builtin_classes", [])}
    singletons = {s["name"]: s for s in data.get("singletons", [])}

    # C17: index utility_functions, global_enums, global_constants.
    utility_functions = {f["name"]: f for f in data.get("utility_functions", [])}
    global_enums = {e["name"]: e for e in data.get("global_enums", [])}
    global_constants = {k["name"]: k for k in data.get("global_constants", [])}

    # Case-insensitive name map covers classes + builtins + utility_functions +
    # global_enums + global_constants so get_class/get_member can resolve any of them.
    ci: dict[str, str] = {}
    for k in list(classes) + list(builtins):
        ci[k.lower()] = k
    for k in list(utility_functions) + list(global_enums) + list(global_constants):
        ci[k.lower()] = k

    _cache = {
        "_mtime": file_mtime,
        "raw": data,
        "classes": classes,
        "builtins": builtins,
        "singletons": singletons,
        "utility_functions": utility_functions,
        "global_enums": global_enums,
        "global_constants": global_constants,
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


def _corrupt_msg() -> str:
    return (
        "extension_api.json is corrupt or unparseable.\n"
        "Re-run dump_api to regenerate the API dump:\n"
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


def _desc(text: str, n: int, full_docs: bool) -> str:
    """Render a doc description: first sentence by default, full (char-capped)
    text when ``full_docs`` is True. The existing char-budget cap (C22) always
    applies on top via ``_trunc`` — first-sentence just changes what goes in."""
    if not full_docs:
        text = docs.first_sentence(text)
    return _trunc(text, n)


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


def _format_property(p: dict[str, Any]) -> str:
    """Format a property line, omitting getter/setter when both are None (C22)."""
    getter = p.get("getter")
    setter = p.get("setter")
    base = f'property {p["name"]}: {_pretty_type(p.get("type"))}'
    if getter is None and setter is None:
        return base
    return f'{base} (get {getter}, set {setter})'


def get_class(name: str, include_inherited: bool = False, full_docs: bool = False) -> str:
    idx = _load()
    if idx.get("_missing"):
        return _missing_msg()
    if idx.get("_corrupt"):
        return _corrupt_msg()

    real = idx["ci"].get(name.lower())
    if not real:
        return f'Class "{name}" not found. Try godot_search("{name}").'

    # C17: handle utility function lookup
    if real in idx.get("utility_functions", {}):
        uf = idx["utility_functions"][real]
        args = []
        for a in uf.get("arguments", []):
            s = f'{a["name"]}: {_pretty_type(a.get("type"))}'
            args.append(s)
        if uf.get("is_vararg"):
            args.append("...")
        ret = _pretty_type(uf.get("return_type"))
        return (
            f'utility func {real}({", ".join(args)}) -> {ret}\n'
            f'  category: {uf.get("category", "unknown")}'
        )

    # C17: handle global enum lookup
    if real in idx.get("global_enums", {}):
        ge = idx["global_enums"][real]
        values = ", ".join(f'{v["name"]}={v["value"]}' for v in ge.get("values", []))
        bitfield = " [bitfield]" if ge.get("is_bitfield") else ""
        return f'global enum {real}{bitfield}: {values}'

    # C17: handle global constant lookup
    if real in idx.get("global_constants", {}):
        gc = idx["global_constants"][real]
        return f'global const {real} = {gc.get("value")}'

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
        lines.append("  " + _desc(dd["brief"] or dd["desc"], 260, full_docs))

    props = c.get("properties") or c.get("members") or []
    if props:
        lines.append("\nProperties:")
        for p in props:
            line = f'  {p["name"]}: {_pretty_type(p.get("type"))}'
            if dd and dd["members"].get(p["name"]):
                line += "  — " + _desc(dd["members"][p["name"]], 90, full_docs)
            lines.append(line)

    methods = c.get("methods") or []
    if methods:
        lines.append("\nMethods:")
        for m in methods:
            line = "  " + _format_method(m)
            if dd and dd["methods"].get(m["name"]):
                line += "   — " + _desc(dd["methods"][m["name"]], 90, full_docs)
            lines.append(line)

    signals = c.get("signals") or []
    if signals:
        lines.append("\nSignals:")
        for s in signals:
            a = ", ".join(f'{x["name"]}: {_pretty_type(x.get("type"))}' for x in s.get("arguments", []))
            line = f'  signal {s["name"]}({a})'
            if dd and dd["signals"].get(s["name"]):
                line += "   — " + _desc(dd["signals"][s["name"]], 90, full_docs)
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
                        line += "   — " + _desc(add["methods"][m["name"]], 80, full_docs)
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

    # C22: apply character budget — cap the response and append a drill-down tail
    # so the agent knows to call godot_member for the full picture.
    result = "\n".join(lines)
    if len(result) > _CLASS_CHAR_BUDGET:
        result = (
            result[:_CLASS_CHAR_BUDGET].rstrip()
            + f"\n…(response truncated — use godot_member({real!r}, member) for details)"
        )
    return result


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
            # C22: omit "(get None, set None)" noise from member listings
            hits.append(_format_property(p))
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


def get_member(class_name: str, member: str, full_docs: bool = False) -> str:
    idx = _load()
    if idx.get("_missing"):
        return _missing_msg()
    if idx.get("_corrupt"):
        return _corrupt_msg()
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
                result += "\n\n" + _desc(desc, 700, full_docs)
                break
    return result


def search(query: str, limit: int = 25) -> str:
    idx = _load()
    if idx.get("_missing"):
        return _missing_msg()
    if idx.get("_corrupt"):
        return _corrupt_msg()
    q = query.lower()

    # C21: hits bucketed by score tier for correct ranking.
    # Score 0 = exact, 1 = prefix, 2 = substring.
    cls_hits: list[tuple[int, str]] = []
    # C21: member/constant/enum hits also carry a score for ranking.
    member_hits: list[tuple[int, str]] = []

    singleton_names = set(idx["singletons"])

    # Engine classes
    for name, c in idx["classes"].items():
        nl = name.lower()
        if q in nl:
            score = 0 if nl == q else (1 if nl.startswith(q) else 2)
            label = f"{name} [singleton]" if name in singleton_names else name
            cls_hits.append((score, label))
        for m in c.get("methods") or []:
            ml = m["name"].lower()
            if q in ml:
                score = 0 if ml == q else (1 if ml.startswith(q) else 2)
                member_hits.append((score, f'{name}.{m["name"]}()'))
        for s in c.get("signals") or []:
            sl = s["name"].lower()
            if q in sl:
                score = 0 if sl == q else (1 if sl.startswith(q) else 2)
                member_hits.append((score, f'{name}.{s["name"]} [signal]'))
        for p in c.get("properties") or []:
            pl = p["name"].lower()
            if q in pl:
                score = 0 if pl == q else (1 if pl.startswith(q) else 2)
                member_hits.append((score, f'{name}.{p["name"]} [property]'))
        # C21: surface class-level enums and constants in search results
        for e in c.get("enums") or []:
            el = e["name"].lower()
            if q in el:
                score = 0 if el == q else (1 if el.startswith(q) else 2)
                member_hits.append((score, f'{name}.{e["name"]} [enum]'))
        for k in c.get("constants") or []:
            kl = k["name"].lower()
            if q in kl:
                score = 0 if kl == q else (1 if kl.startswith(q) else 2)
                member_hits.append((score, f'{name}.{k["name"]} [constant]'))

    # Built-in types (Color, Vector2, …)
    for name, c in idx["builtins"].items():
        nl = name.lower()
        if q in nl:
            score = 0 if nl == q else (1 if nl.startswith(q) else 2)
            cls_hits.append((score, name))
        for m in c.get("methods") or []:
            ml = m["name"].lower()
            if q in ml:
                score = 0 if ml == q else (1 if ml.startswith(q) else 2)
                member_hits.append((score, f'{name}.{m["name"]}()'))
        for mem in c.get("members") or []:
            meml = mem["name"].lower()
            if q in meml:
                score = 0 if meml == q else (1 if meml.startswith(q) else 2)
                member_hits.append((score, f'{name}.{mem["name"]} [property]'))
        for con in c.get("constants") or []:
            conl = con["name"].lower()
            if q in conl:
                score = 0 if conl == q else (1 if conl.startswith(q) else 2)
                member_hits.append((score, f'{name}.{con["name"]} [constant]'))

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

    # C17: utility functions
    for name, uf in idx.get("utility_functions", {}).items():
        nl = name.lower()
        if q in nl:
            score = 0 if nl == q else (1 if nl.startswith(q) else 2)
            cls_hits.append((score, f'{name} [utility_function]'))

    # C17: global enums — surface the enum name AND its value names
    for name, ge in idx.get("global_enums", {}).items():
        nl = name.lower()
        if q in nl:
            score = 0 if nl == q else (1 if nl.startswith(q) else 2)
            cls_hits.append((score, f'{name} [global_enum]'))
        for v in ge.get("values", []):
            vl = v["name"].lower()
            if q in vl:
                score = 0 if vl == q else (1 if vl.startswith(q) else 2)
                member_hits.append((score, f'{name}.{v["name"]} [global_enum_value]'))

    # C17: global constants
    for name in idx.get("global_constants", {}):
        nl = name.lower()
        if q in nl:
            score = 0 if nl == q else (1 if nl.startswith(q) else 2)
            member_hits.append((score, f'{name} [global_constant]'))

    cls_hits.sort()
    member_hits.sort()
    results = [n for _, n in cls_hits] + [n for _, n in member_hits]
    if not results:
        return f'No API matches for "{query}".'
    shown = results[:limit]
    tail = "" if len(results) <= limit else f"\n…({len(results) - limit} more)"
    return "\n".join(shown) + tail
