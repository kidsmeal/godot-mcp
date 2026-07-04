"""procgen: Phase 0 harness for the procgen tool suite (`procgen_*`).

This module is the reconnaissance/harness phase — it proves the round-trip
mechanism the six real tools (`procgen_tileset_build`, `procgen_terrain_audit`,
`procgen_worldgen_preview`, `procgen_island_preview`, `procgen_chunk_lint`,
`procgen_gen_smoke`) will all copy. `ping()` is a throwaway probe; it is
deleted once the first real tool (`procgen_tileset_build`, Phase 1) lands.

Temp-script pattern (decide-once, documented here so later phases copy it
verbatim rather than re-inventing it):

  - Compose a `.gd` source string in Python. It MUST `extends SceneTree` so it
    runs headless via `--script` without popping a blocking editor dialog
    (`runner.run_script` already refuses non-SceneTree/MainLoop scripts for
    this reason; `runner.run_temp_probe` skips that guard because IT is the
    one writing the temp file, so the composed source here always declares
    `extends SceneTree` itself).
  - Hand the source to `runner.run_temp_probe(source, timeout=...)`. That
    helper writes the source to a unique OS-temp `.gd` file, runs it headless
    via the same `_run()` used by every other tool (so GODOT_BIN/GODOT_PROJECT
    resolution, `--log-file` capture, and timeout handling are identical
    across the whole server), and deletes the temp `.gd` (and any `.gd.uid`
    sibling Godot emits) in a `finally` block — no leak into the project or
    OS temp dir even on a crash. Do NOT hand-roll a second subprocess path.
  - The composed script prints a JSON payload on ONE line, wrapped between
    sentinel markers on their own lines:

        print("PROCGEN_JSON_BEGIN")
        print(JSON.stringify({...}))
        print("PROCGEN_JSON_END")

    Python extracts the text strictly between the two sentinel lines with a
    regex and `json.loads()`s it. This is a slightly stronger convention than
    the single-prefix sentinel `project_ground.setting()` uses
    (`__SETTING_VALUE__<value>`) — that one works for a single scalar; a JSON
    payload can itself contain characters (braces, colons) that a naive
    "everything after the marker" scan would need to hand this on the same
    line, so a BEGIN/END pair around a dedicated print is more robust and is
    the pattern the 6 real tools (which all print structured reports) should
    copy.
  - `quit()` at the end of `_initialize()` so the SceneTree exits promptly.
"""
from __future__ import annotations

import json
import re

from godot_mcp import runner

_JSON_RE = re.compile(r"PROCGEN_JSON_BEGIN\s*(.*?)\s*PROCGEN_JSON_END", re.S)

_PING_SCRIPT = (
    "extends SceneTree\n"
    "func _initialize() -> void:\n"
    "\tvar payload := {\n"
    '\t\t"engine_version": Engine.get_version_info().string,\n'
    '\t\t"ok": true,\n'
    "\t}\n"
    '\tprint("PROCGEN_JSON_BEGIN")\n'
    "\tprint(JSON.stringify(payload))\n"
    '\tprint("PROCGEN_JSON_END")\n'
    "\tquit(0)\n"
)


def ping() -> str:
    """Throwaway harness probe: compose a tiny GDScript that prints the engine
    version as JSON between sentinel lines, run it headlessly via the existing
    runner.run_temp_probe machinery, parse the JSON back out, and return a short
    human-readable string. Never raises — degrades to a graceful error string
    if Godot is unavailable, the run times out, or the sentinel/JSON is missing
    or malformed.
    """
    r = runner.run_temp_probe(_PING_SCRIPT, timeout=30)

    if r.get("timeout"):
        return "UNAVAILABLE — procgen harness probe timed out (Godot may be unavailable or stuck)."
    if r.get("rc") is None:
        return f"UNAVAILABLE — {r.get('err') or 'procgen harness probe could not launch Godot.'}"

    out = r.get("out") or ""
    m = _JSON_RE.search(out)
    if not m:
        tail = (r.get("err") or out).strip()
        return f"UNAVAILABLE — procgen harness probe produced no PROCGEN_JSON sentinel block.\n{tail[-500:]}"

    try:
        payload = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        return f"UNAVAILABLE — procgen harness probe printed malformed JSON: {e}"

    version = payload.get("engine_version", "unknown")
    return f"Godot {version} — procgen harness OK"
