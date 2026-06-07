"""Phase 1B tests: probe/validation harness hardening.

Tests for:
  - runner._validate_verdict (pure function, no Godot needed)
  - runner.run_temp_probe cleanup (finally-block leak prevention)
  - runner.validate_with_autoloads containment (refuses escapes before launching Godot)
  - Binary-gated integration tests (skipped when Godot is unavailable)
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from godot_mcp import config


# ---------------------------------------------------------------------------
# Helpers shared across the module
# ---------------------------------------------------------------------------

def _make_run_result(rc: int = 0, out: str = "", err: str = "", timed_out: bool = False) -> dict:
    return {"rc": rc, "out": out, "err": err, "timeout": timed_out}


# ---------------------------------------------------------------------------
# _validate_verdict — pure function unit tests (no Godot required)
# ---------------------------------------------------------------------------

class TestValidateVerdict:
    """Test the pure verdict-parsing function against locked failure markers."""

    def _verdict(self, log: str):
        from godot_mcp.runner import _validate_verdict
        return _validate_verdict(log)

    # --- PASS cases ---------------------------------------------------------

    def test_validate_ok_clean_log_is_pass(self):
        log = "Godot Engine v4.6.2\nVALIDATE_OK\nClosing.\n"
        ok, msg = self._verdict(log)
        assert ok is True
        assert "PASS" in msg

    def test_validate_ok_with_info_lines_is_pass(self):
        """Informational lines must not trigger a FAIL."""
        log = (
            "Godot Engine v4.6.2\n"
            "OpenXR: ...\n"
            "VALIDATE_OK\n"
            "AutoloadSystem loaded\n"
        )
        ok, msg = self._verdict(log)
        assert ok is True

    # --- FAIL cases: VALIDATE_NULL ------------------------------------------

    def test_validate_null_is_fail(self):
        log = "Godot Engine v4.6.2\nVALIDATE_NULL\n"
        ok, msg = self._verdict(log)
        assert ok is False
        assert "VALIDATE_NULL" in msg or "FAIL" in msg

    # --- FAIL cases: error markers in log with VALIDATE_OK ------------------

    def test_parse_error_is_fail(self):
        log = "VALIDATE_OK\nparse_error:1 - Parse Error: Expected ')'\n"
        ok, msg = self._verdict(log)
        assert ok is False

    def test_script_error_is_fail(self):
        log = "VALIDATE_OK\nSCRIPT ERROR: Invalid get index 'x' on base 'Nil'.\n"
        ok, msg = self._verdict(log)
        assert ok is False

    def test_compile_error_is_fail(self):
        log = "VALIDATE_OK\nCompile Error: ...\n"
        ok, msg = self._verdict(log)
        assert ok is False

    def test_not_declared_is_fail(self):
        log = "VALIDATE_OK\nIdentifier 'MyAutoload' not declared in the current scope.\n"
        ok, msg = self._verdict(log)
        assert ok is False

    def test_could_not_find_is_fail(self):
        log = "VALIDATE_OK\nCould not find script 'res://missing.gd'\n"
        ok, msg = self._verdict(log)
        assert ok is False

    def test_could_not_load_is_fail(self):
        log = "VALIDATE_OK\nCould not load script 'res://bad.gd'\n"
        ok, msg = self._verdict(log)
        assert ok is False

    def test_error_markers_are_case_insensitive(self):
        """Markers match regardless of case (engine output varies)."""
        log = "VALIDATE_OK\nparse error: something went wrong\n"
        ok, msg = self._verdict(log)
        assert ok is False

    def test_validate_noarg_is_fail(self):
        """VALIDATE_NOARG indicates caller bug — treat as FAIL."""
        log = "VALIDATE_NOARG\n"
        ok, msg = self._verdict(log)
        assert ok is False

    def test_no_validate_marker_is_fail(self):
        """Log with no VALIDATE_* marker means harness never ran — FAIL."""
        log = "Godot Engine v4.6.2\nOpening project.\n"
        ok, msg = self._verdict(log)
        assert ok is False


# ---------------------------------------------------------------------------
# run_temp_probe — cleanup (finally-block) verification
# ---------------------------------------------------------------------------

class TestRunTempProbeCleanup:
    """Verify that run_temp_probe deletes the temp .gd (and .gd.uid) in ALL cases."""

    def _capture_temp_path(self, monkeypatch, fake_run_fn) -> list[str]:
        """
        Monkeypatches mkstemp to record the temp path, creates a real .gd.uid
        sibling, monkeypatches _run with fake_run_fn, then calls run_temp_probe.
        Returns [gd_path, uid_path].
        """
        from godot_mcp import runner

        captured_paths: list[str] = []
        real_mkstemp = tempfile.mkstemp

        def spy_mkstemp(suffix="", prefix="", dir=None, text=False):
            fd, path = real_mkstemp(suffix=suffix, prefix=prefix, dir=dir, text=text)
            captured_paths.append(path)
            return fd, path

        monkeypatch.setattr(tempfile, "mkstemp", spy_mkstemp)
        monkeypatch.setattr(runner, "_run", fake_run_fn)

        runner.run_temp_probe(source="extends SceneTree\nfunc _initialize():\n\tquit(0)\n")
        return captured_paths

    def test_cleanup_on_success(self, monkeypatch, tmp_path):
        from godot_mcp import runner

        paths_seen: list[str] = []
        uid_seen: list[str] = []

        real_mkstemp = tempfile.mkstemp

        def spy_mkstemp(suffix="", prefix="", dir=None, text=False):
            fd, path = real_mkstemp(suffix=suffix, prefix=prefix, dir=dir, text=text)
            paths_seen.append(path)
            # Simulate Godot creating a .uid file
            uid_path = path + ".uid"
            Path(uid_path).write_text("[uid]\nuid=\"uid://fake\"\n", encoding="utf-8")
            uid_seen.append(uid_path)
            return fd, path

        monkeypatch.setattr(tempfile, "mkstemp", spy_mkstemp)
        monkeypatch.setattr(
            runner, "_run",
            lambda extra_args, timeout: _make_run_result(rc=0, out="Godot Engine\n"),
        )

        runner.run_temp_probe(source="extends SceneTree\nfunc _initialize():\n\tquit(0)\n")

        assert paths_seen, "mkstemp was not called"
        gd_path = paths_seen[0]
        uid_path = uid_seen[0]

        assert not Path(gd_path).exists(), f".gd not deleted after success: {gd_path}"
        assert not Path(uid_path).exists(), f".gd.uid not deleted after success: {uid_path}"

    def test_cleanup_on_exception(self, monkeypatch):
        """Temp file must be deleted even when _run raises."""
        from godot_mcp import runner

        paths_seen: list[str] = []
        uid_seen: list[str] = []

        real_mkstemp = tempfile.mkstemp

        def spy_mkstemp(suffix="", prefix="", dir=None, text=False):
            fd, path = real_mkstemp(suffix=suffix, prefix=prefix, dir=dir, text=text)
            paths_seen.append(path)
            uid_path = path + ".uid"
            Path(uid_path).write_text("[uid]\nuid=\"uid://fake\"\n", encoding="utf-8")
            uid_seen.append(uid_path)
            return fd, path

        monkeypatch.setattr(tempfile, "mkstemp", spy_mkstemp)

        def crashing_run(extra_args, timeout):
            raise RuntimeError("Simulated crash during run")

        monkeypatch.setattr(runner, "_run", crashing_run)

        with pytest.raises(RuntimeError, match="Simulated crash"):
            runner.run_temp_probe(source="extends SceneTree\n")

        assert paths_seen, "mkstemp was not called"
        gd_path = paths_seen[0]
        uid_path = uid_seen[0]

        assert not Path(gd_path).exists(), f".gd not deleted after crash: {gd_path}"
        assert not Path(uid_path).exists(), f".gd.uid not deleted after crash: {uid_path}"


# ---------------------------------------------------------------------------
# validate_with_autoloads — containment tests (no Godot launch allowed)
# ---------------------------------------------------------------------------

class TestValidateWithAutoloadsContainment:
    """Escaped paths must be refused BEFORE any Godot launch."""

    @pytest.fixture()
    def tmp_project(self, tmp_path_factory, monkeypatch):
        proj = tmp_path_factory.mktemp("project")
        (proj / "project.godot").write_text("[gd_resource]\n", encoding="utf-8")
        monkeypatch.setattr(config, "PROJECT_ROOT", proj)
        return proj

    @pytest.fixture()
    def outside_file(self, tmp_path_factory):
        outer = tmp_path_factory.mktemp("outside")
        f = outer / "evil.gd"
        f.write_text("extends Node\n", encoding="utf-8")
        return f

    def _assert_refused_no_launch(self, result: str, monkeypatch, run_called: list) -> None:
        assert isinstance(result, str)
        assert result.startswith("Refused:"), f"Expected Refused:, got: {result!r}"
        assert not run_called, "_run must NOT be called for an escaped path"

    def test_dotdot_escape_refused(self, tmp_project, monkeypatch):
        from godot_mcp import runner
        run_called: list = []
        monkeypatch.setattr(runner, "_run", lambda *a, **kw: run_called.append(a) or {})
        result = runner.validate_with_autoloads("../../evil.gd")
        self._assert_refused_no_launch(result, monkeypatch, run_called)

    def test_absolute_outside_refused(self, tmp_project, outside_file, monkeypatch):
        from godot_mcp import runner
        run_called: list = []
        monkeypatch.setattr(runner, "_run", lambda *a, **kw: run_called.append(a) or {})
        result = runner.validate_with_autoloads(str(outside_file))
        self._assert_refused_no_launch(result, monkeypatch, run_called)

    def test_not_found_returns_not_found(self, tmp_project, monkeypatch):
        """An in-project path that doesn't exist returns 'Not found:' not 'Refused:'."""
        from godot_mcp import runner
        run_called: list = []
        monkeypatch.setattr(runner, "_run", lambda *a, **kw: run_called.append(a) or {})
        result = runner.validate_with_autoloads("res://nonexistent.gd")
        assert "Not found" in result
        assert not run_called


# ---------------------------------------------------------------------------
# godot_validate — tool smoke (no Godot)
# ---------------------------------------------------------------------------

class TestGodotValidateTool:
    """The server.py tool delegates to runner.validate_with_autoloads correctly."""

    @pytest.fixture()
    def tmp_project(self, tmp_path_factory, monkeypatch):
        proj = tmp_path_factory.mktemp("project")
        (proj / "project.godot").write_text("[gd_resource]\n", encoding="utf-8")
        monkeypatch.setattr(config, "PROJECT_ROOT", proj)
        return proj

    def test_server_tool_refuses_escape(self, tmp_project, monkeypatch):
        from godot_mcp import runner
        run_called: list = []
        monkeypatch.setattr(runner, "_run", lambda *a, **kw: run_called.append(a) or {})
        from godot_mcp.server import godot_validate
        result = godot_validate("../../evil.gd")
        assert result.startswith("Refused:")
        assert not run_called

    def test_server_tool_delegates_to_runner(self, tmp_project, monkeypatch):
        """When path is in-project and exists, tool must delegate (not run _run itself)."""
        from godot_mcp import runner
        proj = tmp_project
        script = proj / "my_script.gd"
        script.write_text("extends SceneTree\n", encoding="utf-8")

        validate_called: list = []
        real_validate = runner.validate_with_autoloads

        def spy_validate(script_path, timeout=60):
            validate_called.append(script_path)
            return "PASS  res://my_script.gd"

        monkeypatch.setattr(runner, "validate_with_autoloads", spy_validate)
        from godot_mcp.server import godot_validate
        result = godot_validate("res://my_script.gd")
        assert validate_called, "server tool did not call runner.validate_with_autoloads"
        assert "PASS" in result


# ---------------------------------------------------------------------------
# Binary-gated integration: skipped when Godot is not available
# ---------------------------------------------------------------------------

_godot_available = bool(config.resolve_godot() and Path(config.resolve_godot()[0]).exists())


@pytest.mark.skipif(not _godot_available, reason="Godot binary not resolvable on this machine")
class TestValidateWithAutoloadsIntegration:
    """These tests actually launch Godot — skipped if the binary is absent."""

    @pytest.fixture()
    def tmp_project(self, tmp_path_factory, monkeypatch):
        proj = tmp_path_factory.mktemp("project")
        (proj / "project.godot").write_text(
            "[gd_resource]\n[application]\nconfig/name=\"TestProject\"\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(config, "PROJECT_ROOT", proj)
        return proj

    def test_validate_ok_script(self, tmp_project):
        from godot_mcp import runner
        script = tmp_project / "valid.gd"
        script.write_text("extends Node\nfunc _ready() -> void:\n\tpass\n", encoding="utf-8")
        result = runner.validate_with_autoloads("res://valid.gd")
        assert isinstance(result, str)
        # Should produce either PASS or FAIL — not an import error
        assert "PASS" in result or "FAIL" in result
