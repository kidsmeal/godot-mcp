"""Containment regression tests for Phase 1.

Every path-taking tool must refuse ../ escapes, absolute outside-project
paths, and (where available) symlink-escapes BEFORE reading any file or
launching Godot.

Isolation: a minimal temp project dir is created for each test; config.PROJECT_ROOT
is monkeypatched so resolve_project_path checks against it.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from godot_mcp import config

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_project(tmp_path_factory, monkeypatch):
    """A minimal Godot project tree: just project.godot.
    config.PROJECT_ROOT is repointed here so resolve_project_path uses it.
    Never touches the real capsulecastle project.
    Uses tmp_path_factory so the project dir is distinct from the 'outside' dir.
    """
    proj = tmp_path_factory.mktemp("project")
    (proj / "project.godot").write_text("[gd_resource]\n", encoding="utf-8")
    monkeypatch.setattr(config, "PROJECT_ROOT", proj)
    return proj


@pytest.fixture()
def outside_file(tmp_path_factory):
    """A file that lives OUTSIDE the project tmp dir — used as the absolute-path target.
    Uses a separate tmp dir so it is genuinely outside the monkeypatched PROJECT_ROOT.
    """
    outer = tmp_path_factory.mktemp("outside")
    f = outer / "secret.gd"
    f.write_text("# secret\nextends SceneTree\n", encoding="utf-8")
    return f


@pytest.fixture()
def outside_tscn(tmp_path_factory):
    """A .tscn outside the project."""
    outer = tmp_path_factory.mktemp("outside_tscn")
    f = outer / "secret.tscn"
    f.write_text("[gd_scene format=3]\n[node name=\"Root\" type=\"Node\"]\n", encoding="utf-8")
    return f


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REFUSED_PREFIX = "Refused:"


def assert_refused(result: str, path_hint: str = "") -> None:
    """Assert the tool returned a refusal string and not an error or real content."""
    assert isinstance(result, str), f"Expected str result, got {type(result)}"
    assert result.startswith(REFUSED_PREFIX), (
        f"Expected refusal starting with {REFUSED_PREFIX!r}, got: {result!r}"
        + (f"  (hint: {path_hint})" if path_hint else "")
    )


# ---------------------------------------------------------------------------
# godot_lint  (server.py -> edit -> config.resolve_project_path)
# ---------------------------------------------------------------------------

class TestGodotLint:
    def test_dotdot_escape(self, tmp_project):
        from godot_mcp.server import godot_lint
        result = godot_lint("../../etc/passwd")
        assert_refused(result, "dotdot")

    def test_absolute_outside(self, tmp_project, outside_file):
        from godot_mcp.server import godot_lint
        result = godot_lint(str(outside_file))
        assert_refused(result, str(outside_file))

    def test_symlink_escape(self, tmp_project, outside_file):
        link = tmp_project / "symlink_target.gd"
        try:
            link.symlink_to(outside_file)
        except (OSError, NotImplementedError):
            pytest.skip("symlink creation requires admin privileges on this system")
        from godot_mcp.server import godot_lint
        result = godot_lint("res://symlink_target.gd")
        assert_refused(result, "symlink")


# ---------------------------------------------------------------------------
# project_scene  (server.py -> scene.describe -> config.resolve_project_path)
# ---------------------------------------------------------------------------

class TestProjectScene:
    def test_dotdot_escape(self, tmp_project):
        from godot_mcp.server import project_scene
        result = project_scene("../../some.tscn")
        assert_refused(result, "dotdot")

    def test_absolute_outside(self, tmp_project, outside_tscn):
        from godot_mcp.server import project_scene
        result = project_scene(str(outside_tscn))
        assert_refused(result, str(outside_tscn))

    def test_symlink_escape(self, tmp_project, outside_tscn):
        link = tmp_project / "symlink.tscn"
        try:
            link.symlink_to(outside_tscn)
        except (OSError, NotImplementedError):
            pytest.skip("symlink creation requires admin privileges on this system")
        from godot_mcp.server import project_scene
        result = project_scene("res://symlink.tscn")
        assert_refused(result, "symlink")


# ---------------------------------------------------------------------------
# godot_lint_scene  (server.py -> scene.lint_scene -> config.resolve_project_path)
# ---------------------------------------------------------------------------

class TestGodotLintScene:
    def test_dotdot_escape(self, tmp_project):
        from godot_mcp.server import godot_lint_scene
        result = godot_lint_scene("../../some.tscn")
        assert_refused(result, "dotdot")

    def test_absolute_outside(self, tmp_project, outside_tscn):
        from godot_mcp.server import godot_lint_scene
        result = godot_lint_scene(str(outside_tscn))
        assert_refused(result, str(outside_tscn))

    def test_symlink_escape(self, tmp_project, outside_tscn):
        link = tmp_project / "symlink.tscn"
        try:
            link.symlink_to(outside_tscn)
        except (OSError, NotImplementedError):
            pytest.skip("symlink creation requires admin privileges on this system")
        from godot_mcp.server import godot_lint_scene
        result = godot_lint_scene("res://symlink.tscn")
        assert_refused(result, "symlink")


# ---------------------------------------------------------------------------
# godot_check  (server.py -> runner.check_script -> config.resolve_project_path)
# Must refuse WITHOUT launching Godot.
# ---------------------------------------------------------------------------

class TestGodotCheck:
    def test_dotdot_escape_no_subprocess(self, tmp_project, monkeypatch):
        launched = []
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: launched.append(a) or None)
        from godot_mcp.server import godot_check
        result = godot_check("../../evil.gd")
        assert_refused(result, "dotdot")
        assert not launched, "Godot must NOT be launched for an escaped path"

    def test_absolute_outside_no_subprocess(self, tmp_project, outside_file, monkeypatch):
        launched = []
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: launched.append(a) or None)
        from godot_mcp.server import godot_check
        result = godot_check(str(outside_file))
        assert_refused(result, str(outside_file))
        assert not launched, "Godot must NOT be launched for an escaped path"

    def test_symlink_escape_no_subprocess(self, tmp_project, outside_file, monkeypatch):
        link = tmp_project / "symlink_check.gd"
        try:
            link.symlink_to(outside_file)
        except (OSError, NotImplementedError):
            pytest.skip("symlink creation requires admin privileges on this system")
        launched = []
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: launched.append(a) or None)
        from godot_mcp.server import godot_check
        result = godot_check("res://symlink_check.gd")
        assert_refused(result, "symlink")
        assert not launched


# ---------------------------------------------------------------------------
# godot_run_script  (server.py -> runner.run_script -> config.resolve_project_path)
# Must refuse WITHOUT launching Godot.
# ---------------------------------------------------------------------------

class TestGodotRunScript:
    def test_dotdot_escape_no_subprocess(self, tmp_project, monkeypatch):
        launched = []
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: launched.append(a) or None)
        from godot_mcp.server import godot_run_script
        result = godot_run_script("../../evil.gd")
        assert_refused(result, "dotdot")
        assert not launched

    def test_absolute_outside_no_subprocess(self, tmp_project, outside_file, monkeypatch):
        launched = []
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: launched.append(a) or None)
        from godot_mcp.server import godot_run_script
        result = godot_run_script(str(outside_file))
        assert_refused(result, str(outside_file))
        assert not launched

    def test_symlink_escape_no_subprocess(self, tmp_project, outside_file, monkeypatch):
        link = tmp_project / "symlink_run.gd"
        try:
            link.symlink_to(outside_file)
        except (OSError, NotImplementedError):
            pytest.skip("symlink creation requires admin privileges on this system")
        launched = []
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: launched.append(a) or None)
        from godot_mcp.server import godot_run_script
        result = godot_run_script("res://symlink_run.gd")
        assert_refused(result, "symlink")
        assert not launched


# ---------------------------------------------------------------------------
# godot_write_script  (server.py -> edit.write_script -> config.resolve_project_path)
# ---------------------------------------------------------------------------

class TestGodotWriteScript:
    def test_dotdot_escape(self, tmp_project):
        from godot_mcp.server import godot_write_script
        result = godot_write_script("../../evil.gd", "extends Node\n")
        assert_refused(result, "dotdot")

    def test_absolute_outside(self, tmp_project, outside_file):
        from godot_mcp.server import godot_write_script
        target = str(outside_file)
        result = godot_write_script(target, "extends Node\n")
        assert_refused(result, target)

    def test_symlink_escape(self, tmp_project, outside_file):
        link = tmp_project / "symlink_write.gd"
        try:
            link.symlink_to(outside_file)
        except (OSError, NotImplementedError):
            pytest.skip("symlink creation requires admin privileges on this system")
        from godot_mcp.server import godot_write_script
        result = godot_write_script("res://symlink_write.gd", "extends Node\n")
        assert_refused(result, "symlink")


# ---------------------------------------------------------------------------
# godot_patch_script  (server.py -> edit.patch_script -> config.resolve_project_path)
# F-2: must refuse BEFORE reading the file (so outside content is not exposed)
# ---------------------------------------------------------------------------

class TestGodotPatchScript:
    def test_dotdot_escape_no_read(self, tmp_project, outside_file, monkeypatch):
        """Refusal must happen before any file read."""
        reads = []
        original_read_text = config.read_text
        monkeypatch.setattr(config, "read_text", lambda p: reads.append(p) or original_read_text(p))
        from godot_mcp.server import godot_patch_script
        result = godot_patch_script("../../evil.gd", "old", "new")
        assert_refused(result, "dotdot")
        # No path outside project should have been read
        for p in reads:
            try:
                Path(p).relative_to(tmp_project)
            except ValueError:
                pytest.fail(f"read_text was called on an outside-project path: {p}")

    def test_absolute_outside_no_read(self, tmp_project, outside_file, monkeypatch):
        read_called = []
        # Monkeypatch Path.read_text to detect reads of the outside file
        original_path_read_text = Path.read_text
        def spy_read_text(self, **kwargs):
            read_called.append(str(self))
            return original_path_read_text(self, **kwargs)
        monkeypatch.setattr(Path, "read_text", spy_read_text)
        from godot_mcp.server import godot_patch_script
        result = godot_patch_script(str(outside_file), "old", "new")
        assert_refused(result, str(outside_file))
        outside_str = str(outside_file)
        assert outside_str not in read_called, (
            f"outside file was read before refusal: {read_called}"
        )

    def test_symlink_escape(self, tmp_project, outside_file):
        link = tmp_project / "symlink_patch.gd"
        try:
            link.symlink_to(outside_file)
        except (OSError, NotImplementedError):
            pytest.skip("symlink creation requires admin privileges on this system")
        from godot_mcp.server import godot_patch_script
        result = godot_patch_script("res://symlink_patch.gd", "old", "new")
        assert_refused(result, "symlink")


# ---------------------------------------------------------------------------
# godot_fix_script  (server.py -> edit.auto_fix -> config.resolve_project_path)
# F-2: must refuse BEFORE reading the file
# ---------------------------------------------------------------------------

class TestGodotFixScript:
    def test_dotdot_escape_no_read(self, tmp_project, outside_file, monkeypatch):
        original_path_read_text = Path.read_text
        read_called = []
        def spy_read_text(self, **kwargs):
            read_called.append(str(self))
            return original_path_read_text(self, **kwargs)
        monkeypatch.setattr(Path, "read_text", spy_read_text)
        from godot_mcp.server import godot_fix_script
        result = godot_fix_script("../../evil.gd")
        assert_refused(result, "dotdot")

    def test_absolute_outside_no_read(self, tmp_project, outside_file, monkeypatch):
        original_path_read_text = Path.read_text
        read_called = []
        def spy_read_text(self, **kwargs):
            read_called.append(str(self))
            return original_path_read_text(self, **kwargs)
        monkeypatch.setattr(Path, "read_text", spy_read_text)
        from godot_mcp.server import godot_fix_script
        result = godot_fix_script(str(outside_file))
        assert_refused(result, str(outside_file))
        assert str(outside_file) not in read_called, (
            f"outside file read before refusal: {read_called}"
        )

    def test_symlink_escape(self, tmp_project, outside_file):
        link = tmp_project / "symlink_fix.gd"
        try:
            link.symlink_to(outside_file)
        except (OSError, NotImplementedError):
            pytest.skip("symlink creation requires admin privileges on this system")
        from godot_mcp.server import godot_fix_script
        result = godot_fix_script("res://symlink_fix.gd")
        assert_refused(result, "symlink")


# ---------------------------------------------------------------------------
# editor_open_scene  (server.py -> bridge.open_scene, F-3)
# Must refuse BEFORE sending to the editor bridge.
# ---------------------------------------------------------------------------

class TestGodotOpenScene:
    def test_dotdot_escape_no_bridge(self, tmp_project, monkeypatch):
        from godot_mcp import bridge
        sent = []
        monkeypatch.setattr(bridge, "_send", lambda cmd, **kw: sent.append(cmd) or {"ok": True, "opened": "?"})
        from godot_mcp.server import editor_open_scene
        result = editor_open_scene("../../evil.tscn")
        assert_refused(result, "dotdot")
        assert not sent, "bridge._send must NOT be called for an escaped path"

    def test_absolute_outside_no_bridge(self, tmp_project, outside_tscn, monkeypatch):
        from godot_mcp import bridge
        sent = []
        monkeypatch.setattr(bridge, "_send", lambda cmd, **kw: sent.append(cmd) or {"ok": True, "opened": "?"})
        from godot_mcp.server import editor_open_scene
        result = editor_open_scene(str(outside_tscn))
        assert_refused(result, str(outside_tscn))
        assert not sent

    def test_symlink_escape_no_bridge(self, tmp_project, outside_tscn, monkeypatch):
        link = tmp_project / "symlink_open.tscn"
        try:
            link.symlink_to(outside_tscn)
        except (OSError, NotImplementedError):
            pytest.skip("symlink creation requires admin privileges on this system")
        from godot_mcp import bridge
        sent = []
        monkeypatch.setattr(bridge, "_send", lambda cmd, **kw: sent.append(cmd) or {"ok": True, "opened": "?"})
        from godot_mcp.server import editor_open_scene
        result = editor_open_scene("res://symlink_open.tscn")
        assert_refused(result, "symlink")
        assert not sent
