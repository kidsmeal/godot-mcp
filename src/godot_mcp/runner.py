"""Phase 2: headless validation wrappers — the feedback loop.

Runs the project's Godot test suite / scripts headlessly and returns structured
pass/fail so the agent can check its own work. Output is captured via Godot's
--log-file (robust on the Windows GUI build where a stdout pipe can be empty);
pass/fail comes from the process exit code (0 = all passed).

Phase 1B additions:
  validate_with_autoloads  — SceneTree validator via plugin-owned data/validate_script.gd
  run_temp_probe           — per-call generated probe with guaranteed finally-cleanup
  _validate_verdict        — pure verdict parser (unit-testable, no Godot needed)
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

from godot_mcp import config

SUITE_SCENE = config.PROFILE.suite_scene
INTEGRATION_SCENE = config.PROFILE.integration_scene

_MAINLOOP_RE = re.compile(r"^\s*extends\s+(SceneTree|MainLoop)\b", re.M)
_EXTENDS_RE = re.compile(r"^\s*extends\s+(\w+)", re.M)


def _run(extra_args: list[str], timeout: int) -> dict:
    """Launch Godot headless, capturing output via --log-file. Returns
    {rc, out, err, timeout}. rc is the process exit code (None if it never exited)."""
    fd, log_path = tempfile.mkstemp(suffix=".log", prefix="godot_mcp_")
    os.close(fd)
    cmd = (
        config.resolve_godot()
        + ["--headless", "--path", str(config.PROJECT_ROOT), "--log-file", log_path]
        + extra_args
    )
    rc, timed_out, pipe_err = None, False, ""
    try:
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                cwd=str(config.PROJECT_ROOT),
                stdin=subprocess.DEVNULL,
            )
            rc, pipe_err = proc.returncode, proc.stderr or ""
            pipe_out = proc.stdout or ""
        except subprocess.TimeoutExpired as e:
            timed_out = True
            pipe_out = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
            pipe_err = e.stderr.decode("utf-8", "replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
        except FileNotFoundError:
            return {"rc": None, "out": "", "err": f"Godot binary not found ({cmd[0]}). Set GODOT_BIN to the .exe.", "timeout": False}
        except OSError as e:
            return {"rc": None, "out": "", "err": f"OS error launching Godot: {e}", "timeout": False}

        log_text = config.read_text(Path(log_path)) or ""
        out = log_text if log_text.strip() else pipe_out
        return {"rc": rc, "out": out, "err": pipe_err, "timeout": timed_out}
    finally:
        _safe_unlink(log_path)


def _safe_unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _tail(text: str, n: int = 45) -> str:
    return "\n".join(text.strip().splitlines()[-n:])


def _parse_suite(text: str) -> dict:
    out: dict = {}
    m = re.search(r"Files run:\s*(\d+)", text)
    out["files_run"] = int(m.group(1)) if m else None
    m = re.search(r"Tests:\s*(\d+) passed,\s*(\d+) failed", text)
    out["tests_passed"], out["tests_failed"] = (int(m.group(1)), int(m.group(2))) if m else (None, None)
    m = re.search(r"Assertions:\s*(\d+) passed,\s*(\d+) failed", text)
    out["assert_passed"], out["assert_failed"] = (int(m.group(1)), int(m.group(2))) if m else (None, None)
    ff = re.search(r"Failing files:\n((?:\s+-\s*.+\n?)+)", text)
    out["failing_files"] = re.findall(r"-\s*(\S.+)", ff.group(1)) if ff else []
    fa = re.search(r"Failed assertions:\n(.*?)\n=====", text, re.S)
    out["failures"] = [ln.rstrip() for ln in fa.group(1).splitlines() if ln.strip()] if fa else []
    return out


def run_tests(filter: str = "", integration: bool = False, timeout: int = 300) -> str:
    scene = INTEGRATION_SCENE if integration else SUITE_SCENE
    if not scene:
        return f"No {'integration' if integration else 'unit'} test scene configured (set [tests] in godot-mcp.toml)."
    extra = [scene, "--"] + (["--test-filter", filter] if filter else [])
    r = _run(extra, timeout)
    if r["timeout"]:
        return f"TIMED OUT after {timeout}s (large suite — raise timeout or narrow with filter).\n\nLast output:\n{_tail(r['out'] or r['err'])}"
    if r["rc"] is None:
        return r["err"]

    p = _parse_suite(r["out"])
    framework = config.PROFILE.test_framework
    if framework != "custom" or (p.get("files_run") is None and p.get("tests_passed") is None):
        # Non-custom runner (GUT/GdUnit4/…) or a summary we can't parse: trust the exit
        # code and return the raw tail instead of fabricating counts.
        verdict = "PASS" if r["rc"] == 0 else "FAIL"
        return f"{verdict}  (exit {r['rc']}, framework={framework})\n\n{_tail(r['out'] or r['err'], 45)}"
    status = "PASS" if r["rc"] == 0 else "FAIL"
    head = (
        f"{status}  (exit {r['rc']})\n"
        f"Scope: {'integration' if integration else 'unit'}" + (f", filter='{filter}'" if filter else "") + "\n"
        f"Files run: {p.get('files_run')}\n"
        f"Tests: {p.get('tests_passed')} passed, {p.get('tests_failed')} failed\n"
        f"Assertions: {p.get('assert_passed')} passed, {p.get('assert_failed')} failed"
    )
    if r["rc"] == 0:
        return head

    parts = [head]
    if p["failing_files"]:
        parts.append("Failing files:\n" + "\n".join(f"  - {f}" for f in p["failing_files"]))
    if p["failures"]:
        parts.append("Failed assertions:\n" + "\n".join(p["failures"][:40]))
    if not p["failing_files"] and not p["failures"]:
        parts.append("No summary parsed (likely a parse/load error). Raw tail:\n" + _tail(r["out"] + "\n" + r["err"], 50))
    return "\n\n".join(parts)


def run_script(script_path: str, timeout: int = 120) -> str:
    # Guard: the GUI Godot build pops a BLOCKING modal OS alert when --script targets
    # a script that isn't a SceneTree/MainLoop (or fails to load), which can hang the
    # run until the subprocess timeout. Refuse those up front.
    try:
        abs_path = config.resolve_project_path(script_path)
    except config.PathEscapeError:
        return f"Refused: {script_path} resolves outside the project root."
    src = config.read_text(abs_path)
    if src is None:
        return f"Not found: {script_path}"
    if not _MAINLOOP_RE.search(src):
        m = _EXTENDS_RE.search(src)
        ext = m.group(1) if m else "(no extends)"
        return (
            f"Refused: godot_run_script needs a script that `extends SceneTree` or `extends MainLoop` "
            f"(this one extends {ext}). Running other scripts via --script can pop a blocking editor "
            f"dialog. Use godot_check to parse-check it, or godot_run_tests for the suite."
        )
    r = _run(["--script", str(abs_path)], timeout)
    if r["timeout"]:
        return f"TIMED OUT after {timeout}s.\n{_tail(r['out'] or r['err'])}"
    if r["rc"] is None:
        return r["err"]
    status = "OK" if r["rc"] == 0 else f"exit {r['rc']}"
    body = (r["out"] + (("\n--- stderr ---\n" + r["err"]) if r["err"].strip() else "")).strip()
    if len(body) > 4000:
        body = "…(head trimmed)\n" + body[-4000:]
    return f"{status}\n\n{body}"


def check_script(script_path: str, timeout: int = 60) -> str:
    try:
        config.resolve_project_path(script_path)
    except config.PathEscapeError:
        return f"Refused: {script_path} resolves outside the project root."
    r = _run(["--check-only", "--script", script_path], timeout)
    if r["timeout"]:
        return f"UNAVAILABLE — check-only timed out after {timeout}s (Godot may be unavailable)."
    if r["rc"] is None:
        return f"UNAVAILABLE — {r['err']}"
    if r["rc"] == 0 and not r["err"].strip():
        return f"OK  {script_path} parses cleanly."
    msg = (r["err"] or r["out"]).strip()
    if len(msg) > 3000:
        msg = msg[-3000:]
    return f"{'OK' if r['rc'] == 0 else 'ERRORS'} (exit {r['rc']})\n{msg}"


# --- Phase 1B: autoload-aware validation + temp probe -----------------------

# Failure markers to scan for in the engine log (case-insensitive).
# These are locked against Godot 4.x behaviour: ResourceLoader.load() returns
# non-null even on a compile error, so the log is the authoritative signal.
# NOTE: VALIDATE_NULL and VALIDATE_NOARG are harness markers, not error-line
# markers; they are matched separately in _validate_verdict before the scan.
_FAIL_MARKERS = re.compile(
    r"Parse Error"
    r"|SCRIPT ERROR"
    r"|Compile Error"
    r"|not declared"
    r"|Could not find"
    r"|Could not load",
    re.IGNORECASE,
)


def _validate_verdict(log_text: str) -> tuple[bool, str]:
    """Pure function: scan *log_text* for harness markers + failure lines.

    Returns (passed: bool, message: str).
    Rules:
      VALIDATE_OK + no failure markers  → PASS
      VALIDATE_OK + any failure marker  → FAIL (compile/script error)
      VALIDATE_NULL                     → FAIL (resource could not load)
      VALIDATE_NOARG                    → FAIL (caller bug — no path arg)
      No VALIDATE_* marker at all       → FAIL (harness did not complete)

    If the log contains a VALIDATE_START marker, only lines appearing after
    that marker are scanned for failure markers.  Lines before VALIDATE_START
    are engine boot noise (autoload warnings, theme-resource notices, etc.) and
    must not cause false FAILs.  Logs without VALIDATE_START are scanned in
    full for backward compatibility.
    """
    has_ok = "VALIDATE_OK" in log_text
    has_null = bool(re.search(r"VALIDATE_NULL", log_text))
    has_noarg = bool(re.search(r"VALIDATE_NOARG", log_text))

    if has_noarg:
        return False, "FAIL  VALIDATE_NOARG — harness received no script path argument (caller bug)"

    if has_null:
        return False, "FAIL  VALIDATE_NULL — script could not be loaded (missing or unreadable resource)"

    if not has_ok:
        return False, "FAIL  No VALIDATE_* marker in engine log — harness did not complete"

    # has_ok is True — scan only the post-start-marker region when available.
    # VALIDATE_START is printed by the harness immediately before the load call,
    # so any error-shaped lines before it are engine/autoload boot noise.
    if "VALIDATE_START" in log_text:
        _, _, post_start = log_text.partition("VALIDATE_START")
        scan_text = post_start
    else:
        scan_text = log_text

    fail_match = _FAIL_MARKERS.search(scan_text)
    if fail_match:
        lines = scan_text.splitlines()
        fail_lines = [ln for ln in lines if _FAIL_MARKERS.search(ln)]
        detail = "\n".join(fail_lines[:10])
        return False, f"FAIL  Script produced errors:\n{detail}"

    return True, "PASS  Script compiled and loaded without errors"


def validate_with_autoloads(script_path: str, timeout: int = 60) -> str:
    """Validate a project script via the plugin-owned SceneTree harness.

    Boots the full project so autoloads are registered (unlike --check-only),
    then loads the target script and reports PASS/FAIL by scanning the engine log.

    The harness (data/validate_script.gd) runs by absolute path — it is NEVER
    copied into the project, so there is zero leak surface.
    """
    try:
        abs_path = config.resolve_project_path(script_path)
    except config.PathEscapeError:
        return f"Refused: {script_path} resolves outside the project root."

    if not abs_path.exists():
        return f"Not found: {script_path}"

    harness = config.DATA_DIR / "validate_script.gd"
    if not harness.exists():
        return f"Harness missing at {harness} — re-install the plugin or run `git checkout data/validate_script.gd`."

    # C9: pass res://-normalized path to ResourceLoader.load() so Godot can
    # resolve it inside the project.  Absolute and backslash paths are not
    # understood by ResourceLoader — only res:// paths are portable.
    project_root = config.PROJECT_ROOT.resolve()
    rel = abs_path.resolve().relative_to(project_root)
    harness_arg = "res://" + rel.as_posix()

    r = _run(["--script", str(harness), "--", harness_arg], timeout)

    if r["timeout"]:
        return f"TIMED OUT after {timeout}s.\n{_tail(r['out'] or r['err'])}"
    if r["rc"] is None:
        return r["err"]

    passed, verdict = _validate_verdict(r["out"])
    log_tail = _tail(r["out"], 30)
    return f"{verdict}\n\nScript: {script_path}\n\nLog (tail):\n{log_tail}"


def run_temp_probe(
    source: str,
    user_args: list[str] | None = None,
    timeout: int = 60,
) -> dict:
    """Write *source* to a unique OS-temp .gd and run it headless.

    The temp file (and any .gd.uid sibling Godot may emit) are deleted in a
    finally block — a crash mid-run cannot leak the probe into the project or
    any tracked directory.

    Returns the _run dict: {rc, out, err, timeout}.
    """
    fd, gd_path = tempfile.mkstemp(suffix=".gd", prefix="godot_mcp_probe_")
    # C13: close the fd in its own try/finally so an os.write failure cannot
    # leak the file descriptor — the outer finally then handles file cleanup.
    try:
        try:
            os.write(fd, source.encode("utf-8"))
        finally:
            os.close(fd)
        extra: list[str] = ["--script", gd_path]
        if user_args:
            extra += ["--"] + user_args
        return _run(extra, timeout)
    finally:
        _safe_unlink(gd_path)
        _safe_unlink(gd_path + ".uid")
