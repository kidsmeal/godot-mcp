"""Phase 3b: convention-linted, parse-checked GDScript edits.

write_script / patch_script never leave the project in a non-parsing state: they
back up, write, run Godot's --check-only, and ROLL BACK on a parse error. Lint
findings are reported; by default they don't block (regex lint can false-positive),
but enforce_conventions=True will refuse a write that has convention errors.
"""
from __future__ import annotations

import re
from pathlib import Path

from godot_mcp import catalogs, config, lint, project_ground, runner

_UNTYPED_VAR = re.compile(r"^(\s*(?:@\w+(?:\([^)]*\))?\s+)*(?:static\s+)?var\s+\w+)\s*=\s*(?!=)(.*)$")
_FUNC_NO_RET = re.compile(r"^(\s*)((?:@\w+(?:\([^)]*\))?\s+)*(?:static\s+)?func\s+\w+\s*\(.*?\))\s*:\s*$")


def _detect_newline(path: Path) -> str:
    """Return '\r\n' if the file uses CRLF line endings, else '\n'."""
    try:
        raw = path.read_bytes()
        crlf = raw.count(b"\r\n")
        lf = raw.count(b"\n") - crlf
        return "\r\n" if crlf > lf else "\n"
    except OSError:
        return "\n"


def _do_rollback(
    target: Path,
    existed: bool,
    backup: bytes | None,
    created_dirs: list[Path],
) -> None:
    """Restore the file to its pre-write state and remove any empty dirs we created."""
    if existed and backup is not None:
        target.write_bytes(backup)
    else:
        try:
            target.unlink()
        except OSError:
            pass
    # C6: remove empty dirs we created, deepest first
    for d in reversed(created_dirs):
        try:
            d.rmdir()
        except OSError:
            break  # non-empty or permission error — leave the rest


def write_script(res_path: str, content: str, enforce_conventions: bool = False) -> str:
    if not res_path.endswith(".gd"):
        return "Refused: path must be a .gd script (res:// path)."

    try:
        target = config.resolve_project_path(res_path)
    except config.PathEscapeError:
        return f"Refused: {res_path} resolves outside the project root."

    findings = lint.lint_source(
        content,
        res_path,
        catalog_refs=catalogs.build_catalog_refs(),
        input_actions=project_ground.input_action_set(),
    )
    if enforce_conventions and lint.has_errors(findings):
        return (
            "WRITE BLOCKED (enforce_conventions=True) — convention errors:\n"
            + lint.format_findings(findings)
            + "\n\nNothing written."
        )

    existed = target.exists()
    backup = target.read_bytes() if existed else None

    # C6: record which dirs we are about to create so rollback can remove them
    created_dirs: list[Path] = []
    p = target.parent
    while not p.exists():
        created_dirs.insert(0, p)  # shallowest first; reversed() on rollback → deepest first
        p = p.parent

    # C2: preserve the file's original line-ending style on write
    newline = _detect_newline(target) if existed else "\n"

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8", newline=newline)

    # C7: record the mtime of our own write to detect external modification on rollback
    try:
        our_mtime: float | None = target.stat().st_mtime
    except OSError:
        our_mtime = None

    # C1: wrap check_script so any exception triggers a clean rollback (no traceback to caller)
    try:
        check = runner.check_script(res_path)
    except Exception:  # noqa: BLE001
        _do_rollback(target, existed, backup, created_dirs)
        return "WRITE ROLLED BACK — parse check raised an unexpected error. (Restored previous state; no change kept.)"

    if not check.startswith("OK"):
        # C7: detect external modification between our write and rollback
        external_modified = False
        if our_mtime is not None:
            try:
                external_modified = target.stat().st_mtime != our_mtime
            except OSError:
                pass

        _do_rollback(target, existed, backup, created_dirs)

        if check.startswith("UNAVAILABLE"):
            return (
                f"WRITE ROLLED BACK — Godot unavailable (could not verify parse):\n{check}\n\n"
                "(Restored previous state; no change kept.)"
            )

        suffix = (
            "\n\n(WARNING: file was externally modified between write and parse check "
            "— backup restored, external changes may be lost.)"
            if external_modified else ""
        )
        return (
            f"WRITE ROLLED BACK — script does not parse:\n{check}\n\n"
            f"(Restored previous state; no change kept.){suffix}"
        )

    out = [f"WROTE {res_path} ({'updated' if existed else 'created'}) — parses cleanly."]
    out.append(
        "Convention findings"
        + (" (non-blocking)" if not enforce_conventions else "")
        + ":\n"
        + lint.format_findings(findings)
    )
    return "\n\n".join(out)


def patch_script(res_path: str, old_string: str, new_string: str, enforce_conventions: bool = False) -> str:
    try:
        target = config.resolve_project_path(res_path)
    except config.PathEscapeError:
        return f"Refused: {res_path} resolves outside the project root."
    if not target.exists():
        return f"Not found: {res_path}"
    # C3: strict UTF-8 — refuse non-UTF8 files with a clean message
    try:
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"Refused: {res_path} contains non-UTF8 bytes — cannot patch a non-UTF8 file."
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
    if not target.exists():
        return f"Not found: {res_path}"
    # C3: strict UTF-8 — refuse non-UTF8 files with a clean message
    try:
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"Refused: {res_path} contains non-UTF8 bytes — cannot auto-fix a non-UTF8 file."

    lines = text.splitlines()
    fixes: list[str] = []

    # C4: track triple-quoted string state so we don't rewrite content inside """ blocks.
    # A line containing """ toggles whether we're inside a multi-line string.
    # Skip any line that is inside a block or that contains the delimiter itself.
    triple_toggle = 0
    for i, line in enumerate(lines):
        was_in = (triple_toggle % 2 == 1)
        triple_toggle += line.count('"""')
        in_now = (triple_toggle % 2 == 1)
        if was_in or in_now or '"""' in line:
            continue
        m = _UNTYPED_VAR.match(line)
        if m and m.group(2).strip():
            lines[i] = f"{m.group(1)} := {m.group(2)}".rstrip()
            fixes.append(f"L{i + 1}: untyped var -> `:=`")

    triple_toggle = 0
    for i, line in enumerate(lines):
        was_in = (triple_toggle % 2 == 1)
        triple_toggle += line.count('"""')
        in_now = (triple_toggle % 2 == 1)
        if was_in or in_now or '"""' in line:
            continue
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
