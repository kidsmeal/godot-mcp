"""Phase 3a: a GDScript convention linter grounded in this project's AGENTS.md.

It checks the *conventions* that Godot's own --check-only does NOT: strict typing
on every var/param/return, past-tense signals (no on_ prefix), PascalCase
class_name, ALL_CAPS consts, snake_case funcs, and forbidden .godot/imported refs.
Heuristic/regex-based (not a full parser): declaration checks anchor to line start.
"""
from __future__ import annotations

import re
from pathlib import Path

_ANN = r"(?:@\w+(?:\([^)]*\))?\s+)*(?:static\s+)?"
VAR_RE = re.compile(rf"^\s*{_ANN}var\s+(?P<name>[A-Za-z_]\w*)(?P<rest>.*)$")
FUNC_RE = re.compile(rf"^\s*{_ANN}func\s+(?P<name>[A-Za-z_]\w*)\s*\((?P<params>.*?)\)(?P<after>.*)$")
CONST_RE = re.compile(r"^\s*const\s+(?P<name>[A-Za-z_]\w*)")
SIGNAL_RE = re.compile(r"^\s*signal\s+(?P<name>[A-Za-z_]\w*)")
CLASSNAME_RE = re.compile(r"^\s*class_name\s+(?P<name>[A-Za-z_]\w*)")
PLAIN_ASSERT_RE = re.compile(r"(?<![\w.])assert\s*\(")
PASCAL_RE = re.compile(r"[A-Z][A-Za-z0-9]*$")


def _split_params(s: str) -> list[str]:
    parts, depth, cur = [], 0, ""
    for ch in s:
        if ch in "([{":
            depth += 1
            cur += ch
        elif ch in ")]}":
            depth -= 1
            cur += ch
        elif ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur)
    return parts


def lint_source(source: str, path: str = "") -> list[dict]:
    is_test = "/tests/" in path or Path(path).name.startswith("test_")
    findings: list[dict] = []

    def add(line: int, sev: str, rule: str, msg: str) -> None:
        findings.append({"line": line, "severity": sev, "rule": rule, "message": msg})

    for i, line in enumerate(source.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        if ".godot/imported" in line:
            add(i, "error", "path-imported", "references .godot/imported/ — use the source res:// asset path")

        m = VAR_RE.match(line)
        if m:
            name, rest = m.group("name"), m.group("rest").lstrip()
            if not (rest.startswith(":=") or rest.startswith(":")):
                add(i, "error", "typed-var", f"`var {name}` has no type hint (use `{name}: Type` or `{name} := value`)")
            if name != name.lower():
                add(i, "warn", "var-naming", f"variable `{name}` should be snake_case")
            continue

        m = CONST_RE.match(line)
        if m:
            name = m.group("name")
            if name.islower():
                add(i, "warn", "const-naming", f"constant `{name}` should be ALL_CAPS_SNAKE_CASE")
            continue

        m = SIGNAL_RE.match(line)
        if m:
            name = m.group("name")
            if name.startswith("on_"):
                add(i, "warn", "signal-naming", f"signal `{name}` uses `on_` prefix — use a past-tense event name")
            elif name != name.lower():
                add(i, "warn", "signal-naming", f"signal `{name}` should be snake_case past-tense")
            continue

        m = CLASSNAME_RE.match(line)
        if m:
            name = m.group("name")
            if not PASCAL_RE.match(name):
                add(i, "warn", "class-name-pascal", f"class_name `{name}` should be PascalCase")
            continue

        m = FUNC_RE.match(line)
        if m:
            name, params, after = m.group("name"), m.group("params"), m.group("after")
            if name != name.lower():
                add(i, "warn", "func-naming", f"function `{name}` should be snake_case")
            if "->" not in after:
                add(i, "error", "func-return-type", f"function `{name}` is missing a return type (`-> Type`)")
            for p in _split_params(params):
                base = p.split("=", 1)[0].strip()
                if not base or base == "self":
                    continue
                if ":" not in base:
                    add(i, "error", "func-param-untyped", f"parameter `{base}` in `{name}` is untyped")
            continue

        if is_test and PLAIN_ASSERT_RE.search(line):
            add(i, "warn", "plain-assert", "use assert_eq/assert_true/etc., not plain assert()")

    return findings


def format_findings(findings: list[dict]) -> str:
    if not findings:
        return "No convention issues found."
    rows = [
        f'  L{f["line"]}: [{f["severity"]}] {f["rule"]} — {f["message"]}'
        for f in sorted(findings, key=lambda x: (x["line"], x["rule"]))
    ]
    n_err = sum(1 for f in findings if f["severity"] == "error")
    return f"{len(findings)} issue(s): {n_err} error, {len(findings) - n_err} warn\n" + "\n".join(rows)


def has_errors(findings: list[dict]) -> bool:
    return any(f["severity"] == "error" for f in findings)
