"""Phase 3a (v2): GDScript convention linter, grounded in this project's AGENTS.md.

Design (after a review pass):
  * Structural + naming rules run on gdtoolkit's real AST (multi-line correct,
    near-zero false positives). If a file doesn't parse, we fall back to regex.
  * Line scans (forbidden .godot/imported refs, plain assert() in tests) run always.
  * Catalog-aware rule: flags effect_type keys not registered anywhere in the
    project — the bug an LLM actually makes here. Advisory (warn).
  * `# lint: ignore` / `# lint: ignore=rule,rule` suppresses findings on a line.

Godot's own --check-only is errors-only (no untyped-declaration warning), so these
conventions can't be delegated to the compiler — hence this linter.
"""
from __future__ import annotations

import re

try:
    from gdtoolkit.parser import parser as _gp

    _HAS_GP = True
except Exception:  # pragma: no cover
    _HAS_GP = False

PASCAL_RE = re.compile(r"[A-Z][A-Za-z0-9]*$")
SUPPRESS_RE = re.compile(r"#\s*lint:\s*ignore(?:=([\w,\-]+))?")
PLAIN_ASSERT_RE = re.compile(r"(?<![\w.])assert\s*\(")

# Regex fallback (used only when gdtoolkit can't parse a file).
_ANN = r"(?:@\w+(?:\([^)]*\))?\s+)*(?:static\s+)?"
_VAR_RE = re.compile(rf"^\s*{_ANN}var\s+(?P<name>[A-Za-z_]\w*)(?P<rest>.*)$")
_FUNC_RE = re.compile(rf"^\s*{_ANN}func\s+(?P<name>[A-Za-z_]\w*)\s*\((?P<params>.*?)\)(?P<after>.*)$")
_CONST_RE = re.compile(r"^\s*const\s+(?P<name>[A-Za-z_]\w*)")
_SIGNAL_RE = re.compile(r"^\s*signal\s+(?P<name>[A-Za-z_]\w*)")
_CLASSNAME_RE = re.compile(r"^\s*class_name\s+(?P<name>[A-Za-z_]\w*)")


def _f(line, sev, rule, msg):
    return {"line": line or 0, "severity": sev, "rule": rule, "message": msg}


def _check_name_case(name, line, out):
    if name and name != name.lower():
        out.append(_f(line, "warn", "var-naming", f"variable `{name}` should be snake_case"))


# ---------- AST backend ----------
def _node_line(node):
    from lark import Token, Tree

    if isinstance(node, Token):
        return node.line
    if isinstance(node, Tree):
        for c in node.children:
            ln = _node_line(c)
            if ln is not None:
                return ln
    return None


def _first_name(node):
    from lark import Token

    for c in getattr(node, "children", []):
        if isinstance(c, Token):
            return str(c)
    for c in getattr(node, "children", []):
        n = _first_name(c)
        if n:
            return n
    return None


def _ast_findings(tree):
    from lark import Token, Tree

    out: list[dict] = []
    UNTYPED_VAR = {"class_var_assigned", "func_var_assigned"}
    TYPED_VAR = {
        "class_var_typed", "class_var_typed_assgnd", "class_var_inf",
        "func_var_typed", "func_var_typed_assgnd", "func_var_inf",
    }
    CONST = {"const_inf", "const_assigned", "const_typed", "const_typed_assigned", "const_typed_assgnd"}

    for node in tree.iter_subtrees():
        data = str(node.data)
        ln = _node_line(node)

        if data == "classname_stmt":
            name = _first_name(node)
            if name and not PASCAL_RE.match(name):
                out.append(_f(ln, "warn", "class-name-pascal", f"class_name `{name}` should be PascalCase"))

        elif data == "signal_stmt":
            name = _first_name(node)
            if name and name.startswith("on_"):
                out.append(_f(ln, "warn", "signal-naming", f"signal `{name}` uses `on_` prefix — use a past-tense event name"))
            elif name and name != name.lower():
                out.append(_f(ln, "warn", "signal-naming", f"signal `{name}` should be snake_case past-tense"))

        elif data in UNTYPED_VAR:
            name = _first_name(node)
            out.append(_f(ln, "error", "typed-var", f"`var {name}` has no type hint (use `{name}: Type` or `{name} := value`)"))
            _check_name_case(name, ln, out)

        elif data in TYPED_VAR:
            _check_name_case(_first_name(node), ln, out)

        elif data in CONST:
            name = _first_name(node)
            if name and name.islower():
                out.append(_f(ln, "warn", "const-naming", f"constant `{name}` should be ALL_CAPS_SNAKE_CASE"))

        elif data == "func_header":
            name = None
            has_return = False
            args_node = None
            for c in node.children:
                if isinstance(c, Token):
                    if c.type == "NAME" and name is None:
                        name = str(c)
                    elif c.type == "TYPE_HINT":
                        has_return = True
                elif isinstance(c, Tree):
                    if str(c.data) == "func_args":
                        args_node = c
                    else:
                        has_return = True  # complex return type (e.g. Array[int]) is its own subtree
            if name and name != name.lower():
                out.append(_f(ln, "warn", "func-naming", f"function `{name}` should be snake_case"))
            if name and not has_return:
                out.append(_f(ln, "error", "func-return-type", f"function `{name}` is missing a return type (`-> Type`)"))
            if args_node is not None:
                for a in args_node.children:
                    if isinstance(a, Tree) and str(a.data) == "func_arg_regular":
                        out.append(_f(_node_line(a) or ln, "error", "func-param-untyped", f"parameter `{_first_name(a)}` in `{name}` is untyped"))

    return out


# ---------- regex fallback ----------
def _split_params(s):
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


def _regex_findings(source):
    out: list[dict] = []
    for i, line in enumerate(source.splitlines(), start=1):
        if line.lstrip().startswith("#"):
            continue
        m = _VAR_RE.match(line)
        if m:
            name, rest = m.group("name"), m.group("rest").lstrip()
            if not (rest.startswith(":=") or rest.startswith(":")):
                out.append(_f(i, "error", "typed-var", f"`var {name}` has no type hint (use `{name}: Type` or `{name} := value`)"))
            _check_name_case(name, i, out)
            continue
        m = _CONST_RE.match(line)
        if m and m.group("name").islower():
            out.append(_f(i, "warn", "const-naming", f"constant `{m.group('name')}` should be ALL_CAPS_SNAKE_CASE"))
            continue
        m = _SIGNAL_RE.match(line)
        if m:
            name = m.group("name")
            if name.startswith("on_"):
                out.append(_f(i, "warn", "signal-naming", f"signal `{name}` uses `on_` prefix — use a past-tense event name"))
            elif name != name.lower():
                out.append(_f(i, "warn", "signal-naming", f"signal `{name}` should be snake_case past-tense"))
            continue
        m = _CLASSNAME_RE.match(line)
        if m and not PASCAL_RE.match(m.group("name")):
            out.append(_f(i, "warn", "class-name-pascal", f"class_name `{m.group('name')}` should be PascalCase"))
            continue
        m = _FUNC_RE.match(line)
        if m:
            name, params, after = m.group("name"), m.group("params"), m.group("after")
            if name != name.lower():
                out.append(_f(i, "warn", "func-naming", f"function `{name}` should be snake_case"))
            if "->" not in after:
                out.append(_f(i, "error", "func-return-type", f"function `{name}` is missing a return type (`-> Type`)"))
            for p in _split_params(params):
                base = p.split("=", 1)[0].strip()
                if base and base != "self" and ":" not in base:
                    out.append(_f(i, "error", "func-param-untyped", f"parameter `{base}` in `{name}` is untyped"))
    return out


# ---------- always-on line scans ----------
def _line_findings(source, path):
    is_test = "/tests/" in path or path.rsplit("/", 1)[-1].startswith("test_")
    out: list[dict] = []
    for i, line in enumerate(source.splitlines(), start=1):
        if line.lstrip().startswith("#"):
            continue
        if ".godot/imported" in line:
            out.append(_f(i, "error", "path-imported", "references .godot/imported/ — use the source res:// asset path"))
        if is_test and PLAIN_ASSERT_RE.search(line):
            out.append(_f(i, "warn", "plain-assert", "use assert_eq/assert_true/etc., not plain assert()"))
    return out


def _lev(a: str, b: str, cap: int = 2) -> int:
    """Bounded Levenshtein distance; returns cap+1 if it exceeds cap."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        row_min = i
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
            row_min = min(row_min, cur[-1])
        if row_min > cap:
            return cap + 1
        prev = cur
    return prev[-1]


def _catalog_findings(source, catalog_refs):
    """For each profile catalog-ref {use_pattern, valid_pattern, valid_set}: flag a
    use that is unregistered AND looks like a typo of a registered key (edit distance
    <= 2). Only near-misses are flagged, so novel intentional keys aren't false-positived."""
    if not catalog_refs:
        return []
    out: list[dict] = []
    for ref in catalog_refs:
        try:
            use_rx = re.compile(ref["use_pattern"])
        except re.error:
            continue  # invalid regex in profile — skip this ref (matches catalogs.valid_keys style)
        known = set(ref.get("valid_set", ()))
        if ref.get("valid_pattern"):  # also accept registrations in THIS not-yet-saved source
            known |= set(re.findall(ref["valid_pattern"], source))
        for i, line in enumerate(source.splitlines(), start=1):
            if line.lstrip().startswith("#"):
                continue
            for m in use_rx.finditer(line):
                key = m.group(1)
                if not key or key in known:
                    continue
                best, best_d = None, 3
                for k in known:
                    d = _lev(key, k, 2)
                    if d < best_d:
                        best, best_d = k, d
                        if d == 1:
                            break
                if best_d <= 2:
                    out.append(_f(i, "warn", "unknown-catalog-key", f'&"{key}" is not registered; did you mean &"{best}"?'))
    return out


# Match common Godot input-action call sites.
# Captures the action name string from:
#   Input.is_action_pressed("name"), Input.is_action_just_pressed("name"),
#   Input.is_action_just_released("name"), Input.get_action_strength("name"),
#   InputMap.action_has_event("name"), InputMap.action_erase_event("name"), etc.
# Also matches &"name" bare string-name literals passed in those positions.
_INPUT_ACTION_RX = re.compile(
    r"""(?:Input\.(?:is_action_(?:pressed|just_pressed|just_released)|get_action_strength|get_action_raw_strength|get_axis|get_vector)\s*\(\s*|InputMap\.\w+\s*\(\s*)(?:&?)"([^"]+)""",
    re.X,
)


def _input_action_findings(source: str, input_actions: set[str]) -> list[dict]:
    """Flag input-action string references that are NOT registered AND look like a typo
    (edit distance <= 2) of a registered action. Novel/intentional names are not flagged."""
    if not input_actions:
        return []
    out: list[dict] = []
    for i, line in enumerate(source.splitlines(), start=1):
        if line.lstrip().startswith("#"):
            continue
        for m in _INPUT_ACTION_RX.finditer(line):
            key = m.group(1)
            if not key or key in input_actions:
                continue
            best, best_d = None, 3
            for k in input_actions:
                d = _lev(key, k, 2)
                if d < best_d:
                    best, best_d = k, d
                    if d == 1:
                        break
            if best_d <= 2:
                out.append(_f(i, "warn", "unknown-input-action", f'"{key}" is not a registered input action; did you mean "{best}"?'))
    return out


def _suppressions(source):
    sup: dict[int, set] = {}
    for i, line in enumerate(source.splitlines(), start=1):
        m = SUPPRESS_RE.search(line)
        if m:
            sup[i] = {r.strip() for r in m.group(1).split(",")} if m.group(1) else {"*"}
    return sup


def lint_source(
    source: str,
    path: str = "",
    catalog_refs: list | None = None,
    input_actions: set[str] | None = None,
) -> list[dict]:
    findings: list[dict] = []
    fallback = False
    if _HAS_GP:
        try:
            findings += _ast_findings(_gp.parse(source))
        except Exception:
            findings += _regex_findings(source)
            fallback = True
    else:
        findings += _regex_findings(source)
        fallback = True

    findings += _line_findings(source, path)
    findings += _catalog_findings(source, catalog_refs)
    if input_actions:
        findings += _input_action_findings(source, input_actions)

    sup = _suppressions(source)
    findings = [f for f in findings if not (f["line"] in sup and ("*" in sup[f["line"]] or f["rule"] in sup[f["line"]]))]
    findings.sort(key=lambda x: (x["line"], x["rule"]))
    if fallback:
        findings.insert(0, _f(0, "info", "parser", "gdtoolkit parse failed; used regex fallback (results may be partial)"))
    return findings


def format_findings(findings: list[dict]) -> str:
    if not findings:
        return "No convention issues found."
    rows = [f'  L{f["line"]}: [{f["severity"]}] {f["rule"]} — {f["message"]}' for f in findings]
    n_err = sum(1 for f in findings if f["severity"] == "error")
    n_warn = sum(1 for f in findings if f["severity"] == "warn")
    return f"{len(findings)} issue(s): {n_err} error, {n_warn} warn\n" + "\n".join(rows)


def has_errors(findings: list[dict]) -> bool:
    return any(f["severity"] == "error" for f in findings)
