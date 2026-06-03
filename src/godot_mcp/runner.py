"""Phase 2: headless validation wrappers — the feedback loop.

Runs the project's Godot test suite / scripts headlessly and returns structured
pass/fail so the agent can check its own work. Output is captured via Godot's
--log-file (robust on the Windows GUI build where a stdout pipe can be empty);
pass/fail comes from the process exit code (0 = all passed).
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


def _res_to_abs(res_path: str):
    rel = res_path[len("res://"):] if res_path.startswith("res://") else res_path
    return config.PROJECT_ROOT / rel


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
        _safe_unlink(log_path)
        return {"rc": None, "out": "", "err": f"Godot binary not found ({cmd[0]}). Set GODOT_BIN to the .exe.", "timeout": False}

    log_text = config.read_text(Path(log_path)) or ""
    _safe_unlink(log_path)
    out = log_text if log_text.strip() else pipe_out
    return {"rc": rc, "out": out, "err": pipe_err, "timeout": timed_out}


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
    out["failures"] = [l.rstrip() for l in fa.group(1).splitlines() if l.strip()] if fa else []
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
    src = config.read_text(_res_to_abs(script_path))
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
    r = _run(["--script", script_path], timeout)
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
    r = _run(["--check-only", "--script", script_path], timeout)
    if r["timeout"]:
        return f"TIMED OUT after {timeout}s."
    if r["rc"] is None:
        return r["err"]
    if r["rc"] == 0 and not r["err"].strip():
        return f"OK  {script_path} parses cleanly."
    msg = (r["err"] or r["out"]).strip()
    if len(msg) > 3000:
        msg = msg[-3000:]
    return f"{'OK' if r['rc'] == 0 else 'ERRORS'} (exit {r['rc']})\n{msg}"
