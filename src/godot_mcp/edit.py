"""Phase 3b: convention-linted, parse-checked GDScript edits.

write_script / patch_script never leave the project in a non-parsing state: they
back up, write, run Godot's --check-only, and ROLL BACK on a parse error. Lint
findings are reported; by default they don't block (regex lint can false-positive),
but enforce_conventions=True will refuse a write that has convention errors.
"""
from __future__ import annotations

from pathlib import Path

from godot_mcp import catalogs, config, lint, runner


def _abs(res_path: str) -> Path:
    rel = res_path[len("res://"):] if res_path.startswith("res://") else res_path
    return config.PROJECT_ROOT / rel


def write_script(res_path: str, content: str, enforce_conventions: bool = False) -> str:
    if not res_path.endswith(".gd"):
        return "Refused: path must be a .gd script (res:// path)."

    findings = lint.lint_source(content, res_path, catalog_refs=catalogs.build_catalog_refs())
    if enforce_conventions and lint.has_errors(findings):
        return (
            "WRITE BLOCKED (enforce_conventions=True) — convention errors:\n"
            + lint.format_findings(findings)
            + "\n\nNothing written."
        )

    target = _abs(res_path)
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
    target = _abs(res_path)
    if not target.exists():
        return f"Not found: {res_path}"
    text = target.read_text(encoding="utf-8")
    count = text.count(old_string)
    if count == 0:
        return "Patch failed: old_string not found (it must match the file exactly)."
    if count > 1:
        return f"Patch ambiguous: old_string appears {count} times — add surrounding context to make it unique."
    return write_script(res_path, text.replace(old_string, new_string), enforce_conventions)
