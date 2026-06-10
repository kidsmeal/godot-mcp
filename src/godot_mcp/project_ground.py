"""Project grounding: the target project's own conventions, codebase map, and
a reliable file lister (the thing generic Godot MCPs can't do).

This is what makes the connector *yours*: it serves AGENTS.md rules, the
INDEX codebase map, and a Windows-glob-safe file search keyed to res:// paths.
"""
from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

from godot_mcp import config

# ---------------------------------------------------------------------------
# Hardcoded Godot 4.x built-in ui_* action roster
# ---------------------------------------------------------------------------
_BUILTIN_UI_ACTIONS: frozenset[str] = frozenset({
    # Core navigation / selection
    "ui_accept",
    "ui_select",
    "ui_cancel",
    "ui_focus_next",
    "ui_focus_prev",
    "ui_left",
    "ui_right",
    "ui_up",
    "ui_down",
    "ui_page_up",
    "ui_page_down",
    "ui_home",
    "ui_end",
    # Clipboard / history
    "ui_cut",
    "ui_copy",
    "ui_paste",
    "ui_undo",
    "ui_redo",
    # Text-editing — completion
    "ui_text_completion_query",
    "ui_text_completion_accept",
    "ui_text_completion_replace",
    # Text-editing — newlines / indent
    "ui_text_newline",
    "ui_text_newline_blank",
    "ui_text_newline_above",
    "ui_text_indent",
    "ui_text_dedent",
    # Text-editing — backspace / delete
    "ui_text_backspace",
    "ui_text_backspace_word",
    "ui_text_backspace_all_to_left",
    "ui_text_delete",
    "ui_text_delete_word",
    "ui_text_delete_all_to_right",
    # Text-editing — caret movement
    "ui_text_caret_left",
    "ui_text_caret_word_left",
    "ui_text_caret_line_start",
    "ui_text_caret_right",
    "ui_text_caret_word_right",
    "ui_text_caret_line_end",
    "ui_text_caret_up",
    "ui_text_caret_page_up",
    "ui_text_caret_down",
    "ui_text_caret_page_down",
    "ui_text_caret_document_start",
    "ui_text_caret_document_end",
    "ui_text_caret_add_above",
    "ui_text_caret_add_below",
    # Text-editing — scroll / selection
    "ui_text_scroll_up",
    "ui_text_scroll_down",
    "ui_text_select_all",
    "ui_text_select_word_under_caret",
    "ui_text_add_selection_for_next_occurrence",
    "ui_text_skip_selection_for_next_occurrence",
    "ui_text_clear_carets_and_selection",
    "ui_text_toggle_insert_mode",
    "ui_text_submit",
    # Text-editing — misc
    "ui_menu",
    "ui_unicode_start",
    # Graph editor
    "ui_graph_duplicate",
    "ui_graph_delete",
    "ui_graph_follow_left",
    "ui_graph_follow_right",
    # File dialog
    "ui_filedialog_up_one_level",
    "ui_filedialog_refresh",
    "ui_filedialog_show_hidden",
    "ui_filedialog_delete",
    "ui_filedialog_find",
    "ui_filedialog_focus_path",
    # Color picker
    "ui_colorpicker_delete_preset",
    # Misc UI
    "ui_close_dialog",
    "ui_accessibility_drag_and_drop",
    "ui_focus_mode",
    "ui_swap_input_direction",
})

# Cache for classes() — keyed by _gd_signature()
_classes_cache: tuple | None = None  # (sig, result_str)

_HEADING = re.compile(r"^#{1,6}\s")
_TOP_HEADING = re.compile(r"^#{1,3}\s")


def _sections(text: str) -> list[tuple[str, str]]:
    """Split markdown into (heading, body) pairs."""
    sections: list[tuple[str, str]] = []
    head: str
    body: list[str]
    head, body = "(intro)", []
    for ln in text.splitlines():
        if _HEADING.match(ln):
            sections.append((head, "\n".join(body)))
            head, body = ln.strip(), []
        else:
            body.append(ln)
    sections.append((head, "\n".join(body)))
    return sections


def list_docs() -> str:
    out: list[str] = []
    for name, rel in config.PROFILE.docs.items():
        text = config.read_text(config.PROJECT_ROOT / rel)
        if text is None:
            continue
        heads = [ln.strip() for ln in text.splitlines() if _TOP_HEADING.match(ln)]
        out.append(f"## {name}  ({rel})")
        out.extend(f"  {h}" for h in heads[:60])
    return "\n".join(out) if out else "No known convention docs found under the project root."


def convention(topic: str = "") -> str:
    topic = topic.strip()
    if not topic:
        return (
            "Convention/design docs available. Call project_convention('<topic>') "
            "to pull matching sections.\n\n" + list_docs()
        )
    ql = topic.lower()
    hits: list[str] = []
    for name, rel in config.PROFILE.docs.items():
        text = config.read_text(config.PROJECT_ROOT / rel)
        if not text:
            continue
        for head, body in _sections(text):
            if ql in head.lower() or ql in body.lower():
                snippet = (head + "\n" + body).strip()
                if len(snippet) > 1800:
                    snippet = snippet[:1800] + "\n…(truncated)"
                hits.append(f"### [{name}] {head}\n{snippet}")
    if not hits:
        return f'No sections matching "{topic}". Call project_convention() to list docs.'
    return "\n\n---\n\n".join(hits[:8])


def index() -> str:
    rel = config.PROFILE.docs.get(config.PROFILE.index_doc)
    if not rel:
        return f"No index doc configured (profile index_doc={config.PROFILE.index_doc!r}). Available docs: {', '.join(config.PROFILE.docs) or 'none'}."
    return config.read_text(config.PROJECT_ROOT / rel) or f"{rel} not found."


def find_files(subdir: str = ".", pattern: str = "*", limit: int = 500) -> str:
    """Reliable recursive listing under the project root, returning res:// paths.

    Replaces Windows glob (documented to silently miss files in this project).
    """
    root = config.PROJECT_ROOT.resolve()
    try:
        base = config.resolve_project_path(subdir)
    except config.PathEscapeError:
        return f"Refused: {subdir} resolves outside the project root."
    if not base.exists():
        return f"Path not found: {subdir}"
    skip = {".godot", ".git", ".import", "__pycache__"}
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in skip]
        for fn in filenames:
            if fnmatch.fnmatch(fn, pattern):
                full = Path(dirpath) / fn
                try:
                    rel = full.resolve().relative_to(root)
                    out.append("res://" + str(rel).replace("\\", "/"))
                except ValueError:
                    continue  # symlinked outside the root — skip rather than leak an absolute path
                if len(out) >= limit:
                    return "\n".join(out) + f"\n…(truncated at {limit}; narrow with subdir/pattern)"
    return "\n".join(out) if out else f'No files matching "{pattern}" under {subdir}'


# ---------------------------------------------------------------------------
# input_actions / input_action_set
# ---------------------------------------------------------------------------

def _parse_input_actions() -> set[str]:
    """Parse the [input] section of project.godot and return project-defined action names."""
    pg = config.read_text(config.PROJECT_ROOT / "project.godot") or ""
    m = re.search(r"\[input\](.*?)(?:\n\[|\Z)", pg, re.S)
    if not m:
        return set()
    block = m.group(1)
    # Each action is a key of the form: action_name={  (key before the = sign)
    return set(re.findall(r"^([A-Za-z0-9_]+)\s*=\s*\{", block, re.M))


def input_action_set() -> set[str]:
    """Return the full set of valid action names: project-defined ∪ built-in ui_*."""
    return _parse_input_actions() | set(_BUILTIN_UI_ACTIONS)


def input_actions() -> str:
    """List all input actions: project-defined (from [input]) and built-in ui_* actions."""
    project_actions = sorted(_parse_input_actions())
    builtin_actions = sorted(_BUILTIN_UI_ACTIONS)

    lines: list[str] = []
    if project_actions:
        lines.append(f"Project-defined actions ({len(project_actions)}):")
        lines.extend(f"  {a}" for a in project_actions)
    else:
        lines.append("Project-defined actions: (none)")

    lines.append(f"\nBuilt-in ui_* actions ({len(builtin_actions)}):")
    lines.extend(f"  {a}" for a in builtin_actions)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# setting
# ---------------------------------------------------------------------------

def setting(name: str, resolve: bool = False) -> str:
    """Look up a project setting from project.godot.

    name uses Godot's dotted form: 'application/config/name'.
    The first path component maps to the [section]; the rest form the key.

    resolve=True: optionally resolve via a headless Godot probe.
    Graceful-degrades if Godot is unavailable.
    """
    if not name or "/" not in name:
        # Attempt to find a bare key or return a useful message
        if not name:
            return "No setting name provided."
        # Bare name — try without a section prefix
        pg = config.read_text(config.PROJECT_ROOT / "project.godot") or ""
        m = re.search(rf"^{re.escape(name)}\s*=\s*(.+)$", pg, re.M)
        if m:
            raw = m.group(1).strip()
            return f"{name} = {raw}  (file value)"
        return f"Setting '{name}' not found in project.godot."

    parts = name.split("/")
    section = parts[0]
    key = "/".join(parts[1:])

    pg = config.read_text(config.PROJECT_ROOT / "project.godot") or ""
    # Extract the [section] block
    sec_m = re.search(rf"\[{re.escape(section)}\](.*?)(?:\n\[|\Z)", pg, re.S)
    file_value: str | None = None
    if sec_m:
        block = sec_m.group(1)
        kv_m = re.search(rf"^{re.escape(key)}\s*=\s*(.+)$", block, re.M)
        if kv_m:
            file_value = kv_m.group(1).strip()

    if not resolve:
        if file_value is not None:
            return f"{name} = {file_value}  (file value)"
        return f"Setting '{name}' not found in project.godot (section=[{section}], key={key})."

    # resolve=True: use a headless probe via runner.run_temp_probe
    if not re.fullmatch(r"[A-Za-z0-9_/.\-]+", name):
        return f"Setting name {name!r} contains characters not allowed in a ProjectSettings key."

    from godot_mcp import runner  # avoid circular import at module level

    probe_source = (
        "extends SceneTree\n"
        "func _initialize() -> void:\n"
        f'\tvar v = ProjectSettings.get_setting("{name}", null)\n'
        "\tif v == null:\n"
        '\t\tprint("__SETTING_NOT_FOUND__")\n'
        "\telse:\n"
        '\t\tprint("__SETTING_VALUE__" + str(v))\n'
        "\tquit(0)\n"
    )
    r = runner.run_temp_probe(probe_source, timeout=30)
    if r["rc"] is None or r["timeout"]:
        # Godot unavailable or timed out — fall back to file value
        if file_value is not None:
            return f"{name} = {file_value}  (file value; Godot probe unavailable)"
        return f"Setting '{name}' not found in project.godot; Godot probe also unavailable."

    out = r["out"] or r["err"] or ""
    vm = re.search(r"__SETTING_VALUE__(.+)", out)
    if vm:
        resolved = vm.group(1).strip()
        return f"{name} = {resolved}  (resolved via Godot)"
    if "__SETTING_NOT_FOUND__" in out:
        return f"Setting '{name}' not set (ProjectSettings.get_setting returned null)."
    # Unexpected output — fall back
    if file_value is not None:
        return f"{name} = {file_value}  (file value; probe output unclear: {out[:120]!r})"
    return f"Setting '{name}' not found in project.godot; probe output unclear: {out[:120]!r}"


# ---------------------------------------------------------------------------
# classes  (class_name → res:// scan, _gd_signature cached)
# ---------------------------------------------------------------------------

_SKIP_DIRS = {".godot", ".git", ".import"}
_CLASS_NAME_RE = re.compile(r"^\s*class_name\s+([A-Za-z_][A-Za-z0-9_]*)", re.M)


def _gd_signature() -> tuple[int, float]:
    """Cheap fingerprint of the project's .gd files (count + mtime sum)."""
    count, mtime_sum = 0, 0.0
    for dp, dn, fn in os.walk(config.PROJECT_ROOT):
        dn[:] = [d for d in dn if d not in _SKIP_DIRS]
        for f in fn:
            if f.endswith(".gd"):
                try:
                    mtime_sum += (Path(dp) / f).stat().st_mtime
                    count += 1
                except OSError:
                    pass
    return (count, round(mtime_sum, 3))


def classes() -> str:
    """Scan all project .gd files for class_name declarations.

    Returns 'ClassName  ->  res://path' sorted, cached against the .gd file signature
    so a rescan is skipped when nothing changed.
    """
    global _classes_cache
    sig = _gd_signature()
    if _classes_cache is not None and _classes_cache[0] == sig:
        return _classes_cache[1]

    root = config.PROJECT_ROOT.resolve()
    found: list[tuple[str, str]] = []  # (ClassName, res://path)
    for dp, dn, fn in os.walk(config.PROJECT_ROOT):
        dn[:] = [d for d in dn if d not in _SKIP_DIRS]
        for f in fn:
            if not f.endswith(".gd"):
                continue
            abs_path = Path(dp) / f
            text = config.read_text(abs_path) or ""
            for m in _CLASS_NAME_RE.finditer(text):
                class_name = m.group(1)
                try:
                    rel = abs_path.resolve().relative_to(root)
                    res_path = "res://" + str(rel).replace("\\", "/")
                except ValueError:
                    continue
                found.append((class_name, res_path))

    if not found:
        result = "No class_name declarations found in project .gd files."
    else:
        found.sort(key=lambda x: x[0].lower())
        lines = [f"{cls:<40}  ->  {path}" for cls, path in found]
        result = f"class_name declarations ({len(found)}):\n" + "\n".join(lines)

    _classes_cache = (sig, result)
    return result


# ---------------------------------------------------------------------------
# layers
# ---------------------------------------------------------------------------

def layers() -> str:
    """Parse the [layer_names] section of project.godot.

    Groups named layers by category (2d_physics, 3d_physics, 2d_render,
    3d_render, 2d_navigation, 3d_navigation, avoidance) and shows
    layer_number → name.
    """
    pg = config.read_text(config.PROJECT_ROOT / "project.godot") or ""
    m = re.search(r"\[layer_names\](.*?)(?:\n\[|\Z)", pg, re.S)
    if not m:
        return "No [layer_names] section found in project.godot."

    block = m.group(1)
    # Each line: category/layer_N="Name"
    entries = re.findall(r'^([A-Za-z0-9_]+)/layer_(\d+)\s*=\s*"([^"]*)"', block, re.M)
    if not entries:
        return "No named layers found in [layer_names]."

    # Group by category
    grouped: dict[str, list[tuple[int, str]]] = {}
    for cat, num, label in entries:
        grouped.setdefault(cat, []).append((int(num), label))

    out: list[str] = []
    for cat in sorted(grouped):
        layers_in_cat = sorted(grouped[cat], key=lambda x: x[0])
        out.append(f"{cat}:")
        for num, label in layers_in_cat:
            out.append(f"  layer {num}: {label}")
    return "\n".join(out)
