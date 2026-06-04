"""Phase 3b: convention-linted, parse-checked GDScript edits.

write_script / patch_script never leave the project in a non-parsing state: they
back up, write, run Godot's --check-only, and ROLL BACK on a parse error. Lint
findings are reported; by default they don't block (regex lint can false-positive),
but enforce_conventions=True will refuse a write that has convention errors.
"""
from __future__ import annotations

import re

from godot_mcp import catalogs, config, lint, runner

_UNTYPED_VAR = re.compile(r"^(\s*(?:@\w+(?:\([^)]*\))?\s+)*(?:static\s+)?var\s+\w+)\s*=\s*(?!=)(.*)$")
_FUNC_NO_RET = re.compile(r"^(\s*)((?:@\w+(?:\([^)]*\))?\s+)*(?:static\s+)?func\s+\w+\s*\(.*?\))\s*:\s*$")


def write_script(res_path: str, content: str, enforce_conventions: bool = False) -> str:
    if not res_path.endswith(".gd"):
        return "Refused: path must be a .gd script (res:// path)."

    try:
        target = config.resolve_project_path(res_path)
    except config.PathEscapeError:
        return f"Refused: {res_path} resolves outside the project root."

    findings = lint.lint_source(content, res_path, catalog_refs=catalogs.build_catalog_refs())
    if enforce_conventions and lint.has_errors(findings):
        return (
            "WRITE BLOCKED (enforce_conventions=True) — convention errors:\n"
            + lint.format_findings(findings)
            + "\n\nNothing written."
        )

    existed = target.exists()
    backup = target.read_bytes() if existed else None

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8", newline="\n")

    check = runner.check_script(res_path)
    if not check.startswith("OK"):
        if existed:
            target.write_bytes(backup)  # type: ignore[arg-type]
        else:
            try:
                target.unlink()
            except OSError:
                pass
        return f"WRITE ROLLED BACK — script does not parse:\n{check}\n\n(Restored previous state; no change kept.)"

    out = [f"WROTE {res_path} ({'updated' if existed else 'created'}) — parses cleanly."]
    out.append("Convention findings" + (" (non-blocking)" if not enforce_conventions else "") + ":\n" + lint.format_findings(findings))
    return "\n\n".join(out)


def patch_script(res_path: str, old_string: str, new_string: str, enforce_conventions: bool = False) -> str:
    try:
        target = config.resolve_project_path(res_path)
    except config.PathEscapeError:
        return f"Refused: {res_path} resolves outside the project root."
    if not target.exists():
        return f"Not found: {res_path}"
    text = target.read_text(encoding="utf-8")
    count = text.count(old_string)
    if count == 0:
        return "Patch failed: old_string not found (it must match the file exactly)."
    if count > 1:
        return f"Patch ambiguous: old_string appears {count} times — add surrounding context to make it unique."
    return write_script(res_path, text.replace(old_string, new_string), enforce_conventions)


def auto_fix(res_path: str) -> str:
    """Apply safe, mechanical lint fixes, then write through the parse-checked writer
    (rolls back if it breaks). Fixes: untyped `var x = v` -> `var x := v`; add `-> void`
    to functions with no value-returning `return`."""
    if not res_path.endswith(".gd"):
        return "Refused: path must be a .gd script."
    try:
        target = config.resolve_project_path(res_path)
    except config.PathEscapeError:
        return f"Refused: {res_path} resolves outside the project root."
    text = config.read_text(target)
    if text is None:
        return f"Not found: {res_path}"
    lines = text.splitlines()
    fixes: list[str] = []

    for i, line in enumerate(lines):
        m = _UNTYPED_VAR.match(line)
        if m and m.group(2).strip():
            lines[i] = f"{m.group(1)} := {m.group(2)}".rstrip()
            fixes.append(f"L{i + 1}: untyped var -> `:=`")

    for i, line in enumerate(lines):
        m = _FUNC_NO_RET.match(line)
        if not m or "->" in line:
            continue
        indent = len(m.group(1))
        has_value_return = False
        for bl in lines[i + 1:]:
            if not bl.strip() or bl.lstrip().startswith("#"):
                continue
            if (len(bl) - len(bl.lstrip())) <= indent:
                break
            if re.match(r"^\s*return\s+\S", bl):
                has_value_return = True
                break
        if not has_value_return:
            lines[i] = f"{m.group(1)}{m.group(2)} -> void:"
            fixes.append(f"L{i + 1}: missing return type, added `-> void`")

    if not fixes:
        return "No auto-fixable issues found (untyped `var x = v`, or void funcs missing `-> void`)."

    new_text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    result = write_script(res_path, new_text)
    return f"Applied {len(fixes)} fix(es):\n" + "\n".join("  " + f for f in fixes) + "\n\n--- writer ---\n" + result
