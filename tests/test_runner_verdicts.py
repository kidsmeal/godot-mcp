"""Phase 2 (6.5) tests: validation correctness + env-vs-parse verdict.

Covers C5, C8, C9, C10, C11, C12, C13, C14.
All tests are offline (monkeypatch runner._run / config.resolve_godot — no real Godot).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from godot_mcp import config

# ---------------------------------------------------------------------------
# C5 — UNAVAILABLE verdict: env failure must not say "does not parse"
# ---------------------------------------------------------------------------

class TestCheckScriptUnavailable:
    """check_script returns an UNAVAILABLE-class verdict when Godot is missing."""

    @pytest.fixture()
    def tmp_project(self, tmp_path_factory, monkeypatch):
        proj = tmp_path_factory.mktemp("project")
        (proj / "project.godot").write_text("[gd_resource]\n", encoding="utf-8")
        script = proj / "my_script.gd"
        script.write_text("extends Node\n", encoding="utf-8")
        monkeypatch.setattr(config, "PROJECT_ROOT", proj)
        return proj

    def test_check_script_binary_missing_returns_unavailable(self, tmp_project, monkeypatch):
        """Stub _run to simulate FileNotFoundError path → UNAVAILABLE-class verdict."""
        from godot_mcp import runner

        monkeypatch.setattr(
            runner,
            "_run",
            lambda extra_args, timeout: {
                "rc": None,
                "out": "",
                "err": "Godot binary not found (godot4). Set GODOT_BIN to the .exe.",
                "timeout": False,
            },
        )
        result = runner.check_script("res://my_script.gd")
        assert "UNAVAILABLE" in result, f"expected UNAVAILABLE in: {result!r}"
        assert "does not parse" not in result.lower(), (
            f"env failure must not say 'does not parse': {result!r}"
        )

    def test_check_script_timeout_returns_unavailable(self, tmp_project, monkeypatch):
        """A timeout is an environment failure, not a parse failure."""
        from godot_mcp import runner

        monkeypatch.setattr(
            runner,
            "_run",
            lambda extra_args, timeout: {
                "rc": None,
                "out": "",
                "err": "",
                "timeout": True,
            },
        )
        result = runner.check_script("res://my_script.gd")
        assert "UNAVAILABLE" in result or "TIMED OUT" in result, (
            f"timeout should be reported clearly: {result!r}"
        )
        assert "does not parse" not in result.lower(), (
            f"timeout must not say 'does not parse': {result!r}"
        )


class TestWriteScriptUnavailableVerdict:
    """write_script must NOT say 'WRITE ROLLED BACK — script does not parse'
    when check_script returns an UNAVAILABLE verdict (env failure)."""

    @pytest.fixture()
    def tmp_project(self, tmp_path_factory, monkeypatch):
        proj = tmp_path_factory.mktemp("project")
        (proj / "project.godot").write_text("[gd_resource]\n", encoding="utf-8")
        monkeypatch.setattr(config, "PROJECT_ROOT", proj)
        return proj

    def test_write_script_env_failure_not_parse_failure(self, tmp_project, monkeypatch):
        """When Godot is unavailable, write_script rolls back but labels it env failure."""
        from godot_mcp import edit, runner

        monkeypatch.setattr(
            runner,
            "check_script",
            lambda path, timeout=60: "UNAVAILABLE — Godot binary not found",
        )

        result = edit.write_script("res://test.gd", "extends Node\n")
        # Must NOT say "does not parse"
        assert "does not parse" not in result.lower(), (
            f"env failure wrongly labelled as parse failure: {result!r}"
        )
        # Must explain this is an environment/unavailable issue
        assert "UNAVAILABLE" in result or "unavailable" in result.lower(), (
            f"should mention UNAVAILABLE: {result!r}"
        )
        # File should be rolled back (not kept unchecked)
        script_path = tmp_project / "test.gd"
        assert not script_path.exists(), "write should be rolled back when env unavailable"


# ---------------------------------------------------------------------------
# C8 — _validate_verdict false-FAIL fix: benign autoload lines must not FAIL
# ---------------------------------------------------------------------------

class TestValidateVerdictBenignLines:
    """Autoload noise lines that match _FAIL_MARKERS must not cause false-FAIL."""

    def _verdict(self, log: str):
        from godot_mcp.runner import _validate_verdict
        return _validate_verdict(log)

    def test_autoload_save_file_not_found_with_validate_ok_is_pass(self):
        """'could not find save file' from an autoload during boot must not false-FAIL.

        Autoloads run during engine startup, before the harness _initialize() fires,
        so their warnings appear BEFORE VALIDATE_START in a real engine log.
        The start-marker scan ignores the pre-start region.
        """
        log = (
            "Godot Engine v4.6.2\n"
            "WARNING: UserSettings: could not find save file, using defaults\n"
            "VALIDATE_START\n"
            "VALIDATE_OK\n"
        )
        ok, msg = self._verdict(log)
        assert ok is True, f"benign autoload line caused false FAIL: {msg!r}"

    def test_could_not_find_before_start_marker_is_pass(self):
        """Error-shaped lines appearing BEFORE VALIDATE_START are boot noise — ignore."""
        log = (
            "Godot Engine v4.6.2\n"
            "Could not find theme resource at 'res://theme.tres'\n"
            "VALIDATE_START\n"
            "VALIDATE_OK\n"
        )
        ok, msg = self._verdict(log)
        assert ok is True, f"pre-start noise caused false FAIL: {msg!r}"

    def test_parse_error_after_start_is_still_fail(self):
        """A real parse error after VALIDATE_START must still FAIL."""
        log = (
            "Godot Engine v4.6.2\n"
            "VALIDATE_START\n"
            "Parse Error: Expected ')' at line 5\n"
            "VALIDATE_OK\n"
        )
        ok, msg = self._verdict(log)
        assert ok is False, "real parse error after start should FAIL"

    def test_no_start_marker_still_works_legacy(self):
        """Logs without VALIDATE_START (older harness output) still parse OK."""
        log = "Godot Engine v4.6.2\nVALIDATE_OK\n"
        ok, msg = self._verdict(log)
        assert ok is True, f"clean log without start marker should PASS: {msg!r}"

    def test_no_start_marker_with_error_still_fails(self):
        """Without VALIDATE_START, error lines still cause FAIL (legacy behaviour)."""
        log = "VALIDATE_OK\nParse Error: something\n"
        ok, msg = self._verdict(log)
        assert ok is False

    def test_error_only_after_start_marker_fails(self):
        """Error after start but without VALIDATE_OK → FAIL (no marker)."""
        log = "VALIDATE_START\nParse Error: broken\n"
        ok, msg = self._verdict(log)
        assert ok is False


# ---------------------------------------------------------------------------
# C9 — res:// path normalization for validate_with_autoloads
# ---------------------------------------------------------------------------

class TestValidateWithAutoloadsResPath:
    """The path handed to the harness must be res:// normalized."""

    @pytest.fixture()
    def tmp_project(self, tmp_path_factory, monkeypatch):
        proj = tmp_path_factory.mktemp("project")
        (proj / "project.godot").write_text("[gd_resource]\n", encoding="utf-8")
        script = proj / "player.gd"
        script.write_text("extends Node\n", encoding="utf-8")
        monkeypatch.setattr(config, "PROJECT_ROOT", proj)
        return proj

    def test_bare_relative_path_becomes_res(self, tmp_project, monkeypatch):
        """A bare relative input 'player.gd' → harness arg is 'res://player.gd'."""
        from godot_mcp import runner

        harness_args: list[list[str]] = []

        def spy_run(extra_args, timeout):
            harness_args.append(list(extra_args))
            return {"rc": 0, "out": "VALIDATE_START\nVALIDATE_OK\n", "err": "", "timeout": False}

        monkeypatch.setattr(runner, "_run", spy_run)

        # Write a fake harness so the "harness missing" check passes
        fake_data = tmp_project / "_fake_data"
        fake_data.mkdir()
        (fake_data / "validate_script.gd").write_text("extends SceneTree\n", encoding="utf-8")
        monkeypatch.setattr(config, "DATA_DIR", fake_data)

        runner.validate_with_autoloads("player.gd")

        assert harness_args, "_run was not called"
        args = harness_args[0]
        # The '--' separator is followed by the path passed to the harness
        sep_idx = args.index("--")
        passed_path = args[sep_idx + 1]
        assert passed_path.startswith("res://"), (
            f"bare relative path should be passed as res://, got: {passed_path!r}"
        )

    def test_res_path_passed_as_is(self, tmp_project, monkeypatch):
        """A res:// input is passed unchanged."""
        from godot_mcp import runner

        harness_args: list[list[str]] = []

        def spy_run(extra_args, timeout):
            harness_args.append(list(extra_args))
            return {"rc": 0, "out": "VALIDATE_START\nVALIDATE_OK\n", "err": "", "timeout": False}

        monkeypatch.setattr(runner, "_run", spy_run)

        fake_data = tmp_project / "_fake_data"
        fake_data.mkdir()
        (fake_data / "validate_script.gd").write_text("extends SceneTree\n", encoding="utf-8")
        monkeypatch.setattr(config, "DATA_DIR", fake_data)

        runner.validate_with_autoloads("res://player.gd")

        assert harness_args
        args = harness_args[0]
        sep_idx = args.index("--")
        passed_path = args[sep_idx + 1]
        assert passed_path == "res://player.gd", (
            f"res:// input should be passed as-is, got: {passed_path!r}"
        )

    def test_backslash_abs_path_becomes_res(self, tmp_project, monkeypatch):
        """A Windows-style absolute path inside project → res:// form."""
        from godot_mcp import runner

        harness_args: list[list[str]] = []

        def spy_run(extra_args, timeout):
            harness_args.append(list(extra_args))
            return {"rc": 0, "out": "VALIDATE_START\nVALIDATE_OK\n", "err": "", "timeout": False}

        monkeypatch.setattr(runner, "_run", spy_run)

        fake_data = tmp_project / "_fake_data"
        fake_data.mkdir()
        (fake_data / "validate_script.gd").write_text("extends SceneTree\n", encoding="utf-8")
        monkeypatch.setattr(config, "DATA_DIR", fake_data)

        # Construct an absolute path inside the tmp_project
        abs_path = str(tmp_project / "player.gd")
        runner.validate_with_autoloads(abs_path)

        assert harness_args
        args = harness_args[0]
        sep_idx = args.index("--")
        passed_path = args[sep_idx + 1]
        assert passed_path.startswith("res://"), (
            f"absolute path should become res://, got: {passed_path!r}"
        )


# ---------------------------------------------------------------------------
# C10 — harness missing: actionable message
# ---------------------------------------------------------------------------

class TestValidateWithAutoloadsHarnessMissing:
    """When data/validate_script.gd is absent, return an actionable message."""

    @pytest.fixture()
    def tmp_project(self, tmp_path_factory, monkeypatch):
        proj = tmp_path_factory.mktemp("project")
        (proj / "project.godot").write_text("[gd_resource]\n", encoding="utf-8")
        script = proj / "my.gd"
        script.write_text("extends Node\n", encoding="utf-8")
        monkeypatch.setattr(config, "PROJECT_ROOT", proj)
        return proj

    def test_harness_missing_returns_actionable_message(self, tmp_project, monkeypatch):
        """No validate_script.gd → actionable message with the expected path."""
        from godot_mcp import config as cfg
        from godot_mcp import runner

        run_called: list = []
        monkeypatch.setattr(runner, "_run", lambda *a, **kw: run_called.append(a) or {})

        # Point DATA_DIR to a directory with no validate_script.gd
        empty_data = tmp_project / "_empty_data"
        empty_data.mkdir()
        monkeypatch.setattr(cfg, "DATA_DIR", empty_data)

        result = runner.validate_with_autoloads("res://my.gd")

        assert "harness" in result.lower(), f"should mention harness: {result!r}"
        assert not run_called, "_run must not be called when harness is missing"


# ---------------------------------------------------------------------------
# C11 — try/finally for temp log in _run
# ---------------------------------------------------------------------------

class TestRunTempLogCleanup:
    """_run must clean up the temp log even when subprocess.run raises."""

    def test_permission_error_cleans_up_temp_log(self, monkeypatch, tmp_path):
        """subprocess.run raising PermissionError → _run returns err dict, log gone."""
        import tempfile as _tempfile

        from godot_mcp import runner

        created_logs: list[str] = []
        real_mkstemp = _tempfile.mkstemp

        def spy_mkstemp(suffix="", prefix="", dir=None, text=False):
            fd, path = real_mkstemp(suffix=suffix, prefix=prefix, dir=dir, text=text)
            if suffix == ".log":
                created_logs.append(path)
            return fd, path

        monkeypatch.setattr(_tempfile, "mkstemp", spy_mkstemp)
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: (_ for _ in ()).throw(PermissionError("fake permission denied")),
        )
        # resolve_godot must return something non-empty
        monkeypatch.setattr(config, "GODOT_BIN", "godot_fake.exe")

        result = runner._run(["--check-only", "--script", "test.gd"], 30)

        # Result should be an error dict (graceful degrade)
        assert isinstance(result, dict)
        assert result.get("rc") is None or "err" in result

        # The temp log must be gone
        for log_path in created_logs:
            assert not Path(log_path).exists(), f"temp log not cleaned up: {log_path}"


# ---------------------------------------------------------------------------
# C12 — pass str(abs_path) to --script in run_script
# ---------------------------------------------------------------------------

class TestRunScriptAbsPath:
    """run_script must pass the resolved absolute path (not res:// string) to --script."""

    @pytest.fixture()
    def tmp_project(self, tmp_path_factory, monkeypatch):
        proj = tmp_path_factory.mktemp("project")
        (proj / "project.godot").write_text("[gd_resource]\n", encoding="utf-8")
        script = proj / "runner_test.gd"
        script.write_text(
            "extends SceneTree\nfunc _initialize() -> void:\n\tquit(0)\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(config, "PROJECT_ROOT", proj)
        return proj

    def test_run_script_passes_abs_path_to_godot(self, tmp_project, monkeypatch):
        """The path in --script arg must be an absolute path, not res://."""
        from godot_mcp import runner

        run_args: list[list[str]] = []

        def spy_run(extra_args, timeout):
            run_args.append(list(extra_args))
            return {"rc": 0, "out": "Godot ok\n", "err": "", "timeout": False}

        monkeypatch.setattr(runner, "_run", spy_run)

        runner.run_script("res://runner_test.gd")

        assert run_args, "_run was not called"
        args = run_args[0]
        # Find the --script argument's value
        script_idx = args.index("--script")
        passed_path = args[script_idx + 1]
        assert not passed_path.startswith("res://"), (
            f"run_script should pass abs path not res://, got: {passed_path!r}"
        )
        assert os.path.isabs(passed_path), (
            f"run_script should pass an absolute path, got: {passed_path!r}"
        )


# ---------------------------------------------------------------------------
# C13 — fd closed in own try/finally in run_temp_probe
# ---------------------------------------------------------------------------

class TestRunTempProbeFdLeak:
    """If os.write fails, the fd must still be closed (no fd leak)."""

    def test_fd_closed_on_write_error(self, monkeypatch):
        """os.write raising → fd is still closed (no ResourceWarning / leak)."""
        from godot_mcp import runner

        closed_fds: list[int] = []
        real_close = os.close

        def spy_close(fd: int) -> None:
            closed_fds.append(fd)
            real_close(fd)

        monkeypatch.setattr(os, "close", spy_close)
        monkeypatch.setattr(
            os, "write",
            lambda fd, data: (_ for _ in ()).throw(OSError("fake write error")),
        )

        with pytest.raises(OSError, match="fake write error"):
            runner.run_temp_probe(source="extends SceneTree\n")

        assert closed_fds, "os.close was never called — fd leaked"


# ---------------------------------------------------------------------------
# C14 — refuse cmd /c raw-shim fallback in resolve_godot
# ---------------------------------------------------------------------------

class TestResolveGodotRefusesCmdShim:
    """resolve_godot must refuse the cmd /c fallback with an actionable message."""

    def test_cmd_shim_raises_or_errors(self, monkeypatch, tmp_path):
        """A .cmd shim path whose embedded .exe doesn't exist → refuse, not cmd /c."""
        import shutil as _shutil

        from godot_mcp import config as cfg

        # Write a fake .cmd that has NO .exe path embedded in it
        fake_cmd = tmp_path / "godot.cmd"
        fake_cmd.write_text("@echo off\nrem no exe here\n", encoding="utf-8")

        # Make shutil.which return our fake .cmd
        monkeypatch.setattr(_shutil, "which", lambda name: str(fake_cmd))
        monkeypatch.setattr(cfg, "GODOT_BIN", "godot")

        result = cfg.resolve_godot()
        # Must not return ["cmd", "/c", ...]
        assert result[0] != "cmd", (
            f"resolve_godot must not fall back to cmd /c: {result!r}"
        )

    def test_cmd_shim_with_nonexistent_exe_refuses(self, monkeypatch, tmp_path):
        """A .cmd shim pointing to a non-existent .exe → actionable error, not cmd /c."""
        import shutil as _shutil

        from godot_mcp import config as cfg

        # Write a .cmd that has an .exe path that doesn't exist
        fake_cmd = tmp_path / "godot.cmd"
        fake_cmd.write_text(
            '@echo off\n"C:\\nonexistent\\godot.exe" %*\n', encoding="utf-8"
        )

        monkeypatch.setattr(_shutil, "which", lambda name: str(fake_cmd))
        monkeypatch.setattr(cfg, "GODOT_BIN", "godot")

        result = cfg.resolve_godot()
        # Must not return ["cmd", "/c", ...]
        assert result[0] != "cmd", (
            f"resolve_godot must not fall back to cmd /c for missing exe: {result!r}"
        )
