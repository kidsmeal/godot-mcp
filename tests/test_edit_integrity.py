"""Phase 3 (6.5) tests: edit-path integrity — the rollback promise.

Covers C1 (rollback on exception), C2 (CRLF preservation), C3 (strict UTF-8),
C4 (string-aware auto_fix), C6 (new-dir cleanup on rollback),
C7-partial (mtime check on rollback).

All tests are offline — monkeypatch runner.check_script to a stub.
No real Godot binary is needed.
"""
from __future__ import annotations

import pytest

from godot_mcp import config

# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_project(tmp_path_factory, monkeypatch):
    """A minimal project dir repointed via config.PROJECT_ROOT."""
    proj = tmp_path_factory.mktemp("project")
    (proj / "project.godot").write_text("[gd_resource]\n", encoding="utf-8")
    monkeypatch.setattr(config, "PROJECT_ROOT", proj)
    return proj


# ---------------------------------------------------------------------------
# C1 — rollback on exception from check_script
# ---------------------------------------------------------------------------

class TestRollbackOnException:
    """write_script must restore the original file if check_script raises any exception."""

    def test_existing_file_restored_on_permission_error(self, tmp_project, monkeypatch):
        """check_script raising PermissionError → original bytes restored, clean message."""
        from godot_mcp import edit, runner

        original = b"extends Node\n# original content\n"
        script = tmp_project / "myscript.gd"
        script.write_bytes(original)

        monkeypatch.setattr(
            runner, "check_script",
            lambda path, timeout=60: (_ for _ in ()).throw(PermissionError("fake perm error")),
        )

        result = edit.write_script("res://myscript.gd", "extends Node\n# new content\n")

        # Original bytes must be restored
        assert script.read_bytes() == original, "original bytes must be restored on exception"
        # Result must be a string (not a traceback propagated as exception)
        assert isinstance(result, str)
        # Must not be a raw Python traceback
        assert "Traceback" not in result
        assert "PermissionError" not in result

    def test_new_file_unlinked_on_permission_error(self, tmp_project, monkeypatch):
        """check_script raising PermissionError on a new file → file removed, clean message."""
        from godot_mcp import edit, runner

        script = tmp_project / "newscript.gd"
        assert not script.exists()

        monkeypatch.setattr(
            runner, "check_script",
            lambda path, timeout=60: (_ for _ in ()).throw(PermissionError("denied")),
        )

        result = edit.write_script("res://newscript.gd", "extends Node\n")

        assert not script.exists(), "new file must be removed on rollback"
        assert isinstance(result, str)
        assert "Traceback" not in result

    def test_result_message_is_clean_string(self, tmp_project, monkeypatch):
        """The returned message must be a non-empty string, not a traceback."""
        from godot_mcp import edit, runner

        (tmp_project / "s.gd").write_bytes(b"extends Node\n")

        monkeypatch.setattr(
            runner, "check_script",
            lambda path, timeout=60: (_ for _ in ()).throw(OSError("some OS error")),
        )

        result = edit.write_script("res://s.gd", "extends Node\n# changed\n")
        assert isinstance(result, str) and len(result) > 0
        assert "OSError" not in result, "raw exception class must not appear in message"


# ---------------------------------------------------------------------------
# C2 — CRLF preservation in patch_script
# ---------------------------------------------------------------------------

class TestCrlfPreservation:
    """patch_script must detect CRLF and write back CRLF, not convert to LF."""

    def _stub_check_ok(self, monkeypatch) -> None:
        from godot_mcp import runner
        monkeypatch.setattr(runner, "check_script", lambda path, timeout=60: f"OK  {path} parses cleanly.")

    def test_crlf_lines_stay_crlf_after_patch(self, tmp_project, monkeypatch):
        """Patch one line of a CRLF file; all other lines must keep CRLF."""
        self._stub_check_ok(monkeypatch)
        from godot_mcp import edit

        # Write a file using raw bytes so the CRLF survives
        original_crlf = b"extends Node\r\nvar x = 1\r\nvar y = 2\r\n"
        script = tmp_project / "crlf_test.gd"
        script.write_bytes(original_crlf)

        result = edit.patch_script("res://crlf_test.gd", "var x = 1", "var x = 99")

        assert "WROTE" in result or "patched" in result.lower() or "OK" in result, (
            f"patch should succeed; got: {result!r}"
        )
        written = script.read_bytes()
        # All line endings in the result should be CRLF
        # Count CRLF vs bare LF (LF that is not preceded by CR)
        import re
        crlf_count = written.count(b"\r\n")
        bare_lf_count = len(re.findall(b"(?<!\r)\n", written))
        assert bare_lf_count == 0, (
            f"bare LF found after patching CRLF file: {crlf_count} CRLF, {bare_lf_count} bare LF\nbytes: {written!r}"
        )

    def test_lf_file_stays_lf_after_patch(self, tmp_project, monkeypatch):
        """Patching a pure-LF file must not convert to CRLF."""
        self._stub_check_ok(monkeypatch)
        from godot_mcp import edit

        original_lf = b"extends Node\nvar x = 1\nvar y = 2\n"
        script = tmp_project / "lf_test.gd"
        script.write_bytes(original_lf)

        edit.patch_script("res://lf_test.gd", "var x = 1", "var x = 99")

        written = script.read_bytes()
        assert b"\r\n" not in written, (
            f"LF file must not gain CRLF after patch; bytes: {written!r}"
        )

    def test_patched_line_uses_crlf_in_crlf_file(self, tmp_project, monkeypatch):
        """The patched line itself must also use CRLF in a CRLF file."""
        self._stub_check_ok(monkeypatch)
        from godot_mcp import edit

        original_crlf = b"extends Node\r\nvar x = 1\r\n"
        script = tmp_project / "crlf_patch.gd"
        script.write_bytes(original_crlf)

        edit.patch_script("res://crlf_patch.gd", "var x = 1", "var x = 42")

        written = script.read_bytes()
        assert b"var x = 42\r\n" in written or b"var x = 42" in written, (
            f"patched content missing; bytes: {written!r}"
        )
        import re
        bare_lf = len(re.findall(b"(?<!\r)\n", written))
        assert bare_lf == 0, f"bare LF in patched CRLF file: {written!r}"


# ---------------------------------------------------------------------------
# C3 — strict UTF-8 decode: refuse non-UTF8 files
# ---------------------------------------------------------------------------

class TestStrictUtf8:
    """auto_fix and patch_script must refuse non-UTF8 files with a clean message."""

    def test_auto_fix_refuses_non_utf8(self, tmp_project, monkeypatch):
        """auto_fix on a file with invalid UTF-8 bytes → clean refusal, bytes unchanged."""
        from godot_mcp import edit

        bad_bytes = b"extends Node\n# ok\n\xff\xfe invalid\n"
        script = tmp_project / "bad_utf8.gd"
        script.write_bytes(bad_bytes)

        result = edit.auto_fix("res://bad_utf8.gd")

        # Clean refusal string (not a traceback)
        assert isinstance(result, str)
        assert "Traceback" not in result
        assert "non-utf" in result.lower() or "utf-8" in result.lower() or "refused" in result.lower(), (
            f"expected refusal mentioning UTF-8; got: {result!r}"
        )
        # Bytes on disk must be unchanged (no U+FFFD persisted)
        assert script.read_bytes() == bad_bytes, "bytes on disk must be unchanged for non-UTF8 file"

    def test_patch_script_refuses_non_utf8(self, tmp_project, monkeypatch):
        """patch_script on a file with invalid UTF-8 bytes → clean refusal, bytes unchanged."""
        from godot_mcp import edit

        bad_bytes = b"extends Node\n\x80\x81 garbage\n"
        script = tmp_project / "bad_patch.gd"
        script.write_bytes(bad_bytes)

        result = edit.patch_script("res://bad_patch.gd", "extends Node", "extends Object")

        assert isinstance(result, str)
        assert "Traceback" not in result
        assert "non-utf" in result.lower() or "utf-8" in result.lower() or "refused" in result.lower(), (
            f"expected refusal mentioning UTF-8; got: {result!r}"
        )
        assert script.read_bytes() == bad_bytes, "bytes on disk must be unchanged after refused patch"

    def test_valid_utf8_file_is_not_refused(self, tmp_project, monkeypatch):
        """A valid UTF-8 file must pass through without refusal."""
        from godot_mcp import edit, runner

        monkeypatch.setattr(runner, "check_script", lambda path, timeout=60: f"OK  {path} parses cleanly.")

        # auto_fix on a file with a fixable `var x = 5` statement
        script = tmp_project / "ok_utf8.gd"
        script.write_text("extends Node\nvar x = 5\n", encoding="utf-8")

        result = edit.auto_fix("res://ok_utf8.gd")
        # Should NOT refuse for UTF-8
        assert "non-utf" not in result.lower(), f"clean UTF-8 file wrongly refused: {result!r}"


# ---------------------------------------------------------------------------
# C4 — string-aware auto_fix: don't rewrite var inside triple-quoted strings
# ---------------------------------------------------------------------------

class TestStringAwareAutoFix:
    """auto_fix must not rewrite `var x = 5` that appears inside a triple-quoted string."""

    @pytest.fixture()
    def _stub_check_ok(self, monkeypatch):
        from godot_mcp import runner
        monkeypatch.setattr(runner, "check_script", lambda path, timeout=60: "OK  parse ok.")

    def test_var_inside_triple_string_not_rewritten(self, tmp_project, _stub_check_ok):
        """A `var x = 5` inside triple-quoted string must be left untouched."""
        from godot_mcp import edit

        source = (
            'extends Node\n'
            'var doc = """\n'
            'var x = 5\n'
            '"""\n'
        )
        script = tmp_project / "str_aware.gd"
        script.write_text(source, encoding="utf-8")

        result = edit.auto_fix("res://str_aware.gd")

        written = script.read_text(encoding="utf-8")
        # The triple-string content must be preserved verbatim
        assert 'var x = 5' in written, (
            f"var inside triple string was rewritten; written:\n{written}"
        )
        # auto_fix should report no fixes (the only var is inside a string)
        assert "0 fix" in result or "No auto-fixable" in result, (
            f"expected no fixes; got: {result!r}"
        )

    def test_real_var_statement_still_gets_fixed(self, tmp_project, _stub_check_ok):
        """A real `var x = 5` statement (not inside a string) still gets `:=`."""
        from godot_mcp import edit

        source = (
            'extends Node\n'
            'var x = 5\n'
        )
        script = tmp_project / "real_var.gd"
        script.write_text(source, encoding="utf-8")

        edit.auto_fix("res://real_var.gd")

        written = script.read_text(encoding="utf-8")
        assert 'var x := 5' in written, (
            f"real var statement was not fixed; written:\n{written}"
        )

    def test_var_after_triple_string_is_fixed(self, tmp_project, _stub_check_ok):
        """A `var x = 5` that appears AFTER a triple-quoted string is still fixed."""
        from godot_mcp import edit

        source = (
            'extends Node\n'
            'var doc = """\n'
            'some text\n'
            '"""\n'
            'var x = 5\n'
        )
        script = tmp_project / "after_str.gd"
        script.write_text(source, encoding="utf-8")

        edit.auto_fix("res://after_str.gd")

        written = script.read_text(encoding="utf-8")
        assert 'var x := 5' in written, (
            f"var after triple string should be fixed; written:\n{written}"
        )

    def test_var_inside_and_outside_both_handled(self, tmp_project, _stub_check_ok):
        """Mixed: one var inside a triple string (leave), one outside (fix)."""
        from godot_mcp import edit

        source = (
            'extends Node\n'
            'var doc = """\n'
            'var inner = 1\n'
            '"""\n'
            'var outer = 2\n'
        )
        script = tmp_project / "mixed.gd"
        script.write_text(source, encoding="utf-8")

        edit.auto_fix("res://mixed.gd")

        written = script.read_text(encoding="utf-8")
        assert 'var inner = 1' in written, "var inside triple string must be preserved"
        assert 'var outer := 2' in written, "var outside triple string must be fixed"


# ---------------------------------------------------------------------------
# C6 — new-dir cleanup on rollback
# ---------------------------------------------------------------------------

class TestNewDirCleanupOnRollback:
    """When write_script creates parent dirs for a new file and then rolls back,
    those empty dirs must be removed."""

    def test_empty_parent_dirs_removed_on_rollback(self, tmp_project, monkeypatch):
        """Rollback of a new file in a newly-created subdir removes the empty dir."""
        from godot_mcp import edit, runner

        # check_script returns a non-OK verdict → triggers rollback
        monkeypatch.setattr(
            runner, "check_script",
            lambda path, timeout=60: "ERRORS (exit 1)\nParse Error: broken",
        )

        new_subdir = tmp_project / "subdir" / "deep"
        assert not new_subdir.exists()

        edit.write_script("res://subdir/deep/new.gd", "extends Node\n# broken\n")

        # The script file must not remain
        assert not (new_subdir / "new.gd").exists(), "new file must be removed on rollback"
        # The created dirs must also be gone
        assert not (tmp_project / "subdir").exists(), (
            f"empty parent dir must be removed on rollback; subdir exists: {(tmp_project / 'subdir').exists()}"
        )

    def test_existing_parent_dir_not_removed_on_rollback(self, tmp_project, monkeypatch):
        """Rollback must NOT remove a parent dir that existed before the write."""
        from godot_mcp import edit, runner

        monkeypatch.setattr(
            runner, "check_script",
            lambda path, timeout=60: "ERRORS (exit 1)\nParse Error: broken",
        )

        existing_subdir = tmp_project / "existing"
        existing_subdir.mkdir()
        # Put a sentinel file so the dir is non-empty after rollback
        (existing_subdir / "other.gd").write_text("extends Node\n", encoding="utf-8")

        edit.write_script("res://existing/new.gd", "extends Node\n# broken\n")

        # The existing parent dir must still be there
        assert existing_subdir.exists(), "pre-existing parent dir must not be removed on rollback"
        assert (existing_subdir / "other.gd").exists(), "existing sibling file must survive rollback"

    def test_partial_new_dirs_removed_on_rollback(self, tmp_project, monkeypatch):
        """Only the dirs that were created by this write are removed on rollback."""
        from godot_mcp import edit, runner

        monkeypatch.setattr(
            runner, "check_script",
            lambda path, timeout=60: "ERRORS (exit 1)\nParse Error: broken",
        )

        # Create one level, but not the second
        existing = tmp_project / "existing"
        existing.mkdir()

        edit.write_script("res://existing/new_deep/script.gd", "extends Node\n# broken\n")

        # The newly-created subdir inside existing must be gone
        assert not (existing / "new_deep").exists(), "created subdir must be removed"
        # The pre-existing dir must remain
        assert existing.exists(), "pre-existing dir must not be removed"


# ---------------------------------------------------------------------------
# C7-partial — mtime check on rollback
# ---------------------------------------------------------------------------

class TestMtimeCheckOnRollback:
    """On rollback, if the file was modified externally between backup and rollback,
    warn instead of silently clobbering."""

    def test_external_modification_produces_warning(self, tmp_project, monkeypatch):
        """If mtime changed between backup and rollback, result must contain a warning."""
        from godot_mcp import edit, runner

        original = b"extends Node\n# original\n"
        script = tmp_project / "mtime_test.gd"
        script.write_bytes(original)

        # Capture the mtime before the write
        mtime_before = script.stat().st_mtime

        def check_and_modify(path, timeout=60):
            # Simulate an external modification between check_script and rollback:
            # we change the file's content and bump its mtime.
            script.write_bytes(b"extends Node\n# externally modified\n")
            # Force a different mtime (in case filesystem resolution is coarse)
            # by utime with a clearly different time
            import os
            future = mtime_before + 10.0
            os.utime(script, (future, future))
            return "ERRORS (exit 1)\nParse Error: broken"

        monkeypatch.setattr(runner, "check_script", check_and_modify)

        result = edit.write_script("res://mtime_test.gd", "extends Node\n# new content\n")

        # Result must contain a warning about external modification
        assert isinstance(result, str)
        assert (
            "warn" in result.lower()
            or "external" in result.lower()
            or "modified" in result.lower()
            or "mtime" in result.lower()
            or "changed" in result.lower()
        ), f"expected mtime warning in result; got: {result!r}"

    def test_no_external_modification_normal_rollback(self, tmp_project, monkeypatch):
        """Without external modification, rollback proceeds normally (no spurious warning)."""
        from godot_mcp import edit, runner

        original = b"extends Node\n# original\n"
        script = tmp_project / "no_mtime.gd"
        script.write_bytes(original)

        monkeypatch.setattr(
            runner, "check_script",
            lambda path, timeout=60: "ERRORS (exit 1)\nParse Error: broken",
        )

        result = edit.write_script("res://no_mtime.gd", "extends Node\n# changed\n")

        # Original bytes restored (no external modification)
        assert script.read_bytes() == original, "original bytes should be restored"
        # No spurious mtime warning
        assert "external" not in result.lower() or "mtime" not in result.lower(), (
            f"unexpected mtime warning without external modification: {result!r}"
        )
