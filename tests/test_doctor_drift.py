"""Phase 6.5 Phase 6 tests: doctor drift checks + C23 fingerprint fix.

All tests are fully offline — no Godot binary, no network.

Coverage:
  C17-doctor:
    1. Doctor FAIL when validate_script.gd is missing.
    2. Doctor FAIL when API dump header version doesn't match binary version.
    3. Version match: substring false-positive is fixed (4.1 must NOT pass against 4.10).
    4. Version match: correct version still passes.
    5. Doctor happy path still reports well on a healthy setup.
  C23:
    6. Renaming a class_name file (preserving count and mtime-sum) still detects the change.
    7. project_classes() returns the new path after a rename, not the stale one.
    8. catalogs.valid_keys() detects a rename via the fixed fingerprint.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from godot_mcp import config

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_project(tmp_path: Path) -> Path:
    """Minimal Godot project with project.godot."""
    (tmp_path / "project.godot").write_text(
        '[gd_resource]\n[application]\nconfig/name="DoctorTest"\n'
        'config/features=PackedStringArray("4.6", "Forward Plus")\n',
        encoding="utf-8",
    )
    return tmp_path


def _make_api_dump(tmp_path: Path, major: int = 4, minor: int = 6, patch: int = 2) -> Path:
    """Write a minimal extension_api.json header to the given directory."""
    dump = {
        "header": {
            "version_major": major,
            "version_minor": minor,
            "version_patch": patch,
            "version_status": "stable",
            "version_build": "official",
            "version_full_name": f"Godot Engine v{major}.{minor}.{patch}.stable.official",
            "precision": "single",
        },
        "classes": [],
        "builtin_classes": [],
        "singletons": [],
        "utility_functions": [],
        "global_enums": [],
        "global_constants": [],
    }
    dump_path = tmp_path / "extension_api.json"
    dump_path.write_text(json.dumps(dump), encoding="utf-8")
    return dump_path


# ---------------------------------------------------------------------------
# C17-doctor: harness existence check
# ---------------------------------------------------------------------------

def _clean_profile(monkeypatch, tmp_project: Path):
    """Monkeypatch config.PROFILE to a minimal clean Profile for the tmp project."""
    from godot_mcp.profile import Profile
    prof = Profile(name="DoctorTest")
    monkeypatch.setattr(config, "PROFILE", prof)


class TestDoctorHarnessCheck:
    """Doctor must FAIL when validate_script.gd is missing from DATA_DIR."""

    @pytest.fixture()
    def tmp_project(self, tmp_path_factory, monkeypatch):
        proj = tmp_path_factory.mktemp("doctor_proj")
        _make_project(proj)
        monkeypatch.setattr(config, "PROJECT_ROOT", proj)
        _clean_profile(monkeypatch, proj)
        return proj

    def test_fail_when_harness_missing(self, tmp_project, tmp_path_factory, monkeypatch):
        """A DATA_DIR with no validate_script.gd must produce a harness FAIL."""
        data_dir = tmp_path_factory.mktemp("data_no_harness")
        _make_api_dump(data_dir)
        monkeypatch.setattr(config, "DATA_DIR", data_dir)
        monkeypatch.setattr(config, "EXTENSION_API", data_dir / "extension_api.json")

        from godot_mcp import doctor
        output = doctor.report()
        # The harness check must produce a FAIL line
        lines = output.splitlines()
        harness_fail_lines = [
            ln for ln in lines
            if "FAIL" in ln and ("harness" in ln.lower() or "validate_script" in ln.lower())
        ]
        assert harness_fail_lines, (
            f"Expected a FAIL line for missing harness; got:\n{output}"
        )

    def test_ok_when_harness_present(self, tmp_project, tmp_path_factory, monkeypatch):
        """A DATA_DIR WITH validate_script.gd must NOT produce a harness FAIL."""
        data_dir = tmp_path_factory.mktemp("data_with_harness")
        _make_api_dump(data_dir)
        (data_dir / "validate_script.gd").write_text(
            "extends SceneTree\nfunc _initialize():\n\tquit(0)\n", encoding="utf-8"
        )
        monkeypatch.setattr(config, "DATA_DIR", data_dir)
        monkeypatch.setattr(config, "EXTENSION_API", data_dir / "extension_api.json")

        from godot_mcp import doctor
        output = doctor.report()
        lines = output.splitlines()
        harness_fail_lines = [
            ln for ln in lines
            if "FAIL" in ln and ("harness" in ln.lower() or "validate_script" in ln.lower())
        ]
        assert not harness_fail_lines, (
            f"Unexpected harness FAIL with harness present:\n{output}"
        )

    def test_fail_contributes_to_issue_count(self, tmp_project, tmp_path_factory, monkeypatch):
        """A missing harness must increase the issue count (not 'All good.')."""
        data_dir = tmp_path_factory.mktemp("data_no_harness2")
        _make_api_dump(data_dir)
        monkeypatch.setattr(config, "DATA_DIR", data_dir)
        monkeypatch.setattr(config, "EXTENSION_API", data_dir / "extension_api.json")

        from godot_mcp import doctor
        output = doctor.report()
        assert "All good." not in output, (
            f"'All good.' must not appear with missing harness:\n{output}"
        )


# ---------------------------------------------------------------------------
# C17-doctor: version match fix (substring false-positive)
# ---------------------------------------------------------------------------

class TestDoctorVersionMatch:
    """API header version must use component comparison, not substring match."""

    @pytest.fixture()
    def tmp_project_with_features_410(self, tmp_path_factory, monkeypatch):
        """A project whose features string includes '4.10' (not '4.1')."""
        proj = tmp_path_factory.mktemp("doctor_410")
        (proj / "project.godot").write_text(
            '[gd_resource]\n[application]\nconfig/name="T"\n'
            'config/features=PackedStringArray("4.10", "Forward Plus")\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(config, "PROJECT_ROOT", proj)
        _clean_profile(monkeypatch, proj)
        return proj

    @pytest.fixture()
    def data_dir_with_41_dump(self, tmp_path_factory, monkeypatch):
        """A DATA_DIR whose dump reports version 4.1."""
        data_dir = tmp_path_factory.mktemp("data_41")
        _make_api_dump(data_dir, major=4, minor=1, patch=0)
        (data_dir / "validate_script.gd").write_text("# harness\n", encoding="utf-8")
        monkeypatch.setattr(config, "DATA_DIR", data_dir)
        monkeypatch.setattr(config, "EXTENSION_API", data_dir / "extension_api.json")
        return data_dir

    def test_api_41_vs_project_410_is_fail(
        self, tmp_project_with_features_410, data_dir_with_41_dump, monkeypatch
    ):
        """API dump header '4.1' must NOT pass against project features '4.10'."""
        from godot_mcp import doctor
        output = doctor.report()
        # The version-match line must be FAIL, not OK
        lines = output.splitlines()
        version_lines = [ln for ln in lines if "matches project version" in ln.lower() or ("api" in ln.lower() and "version" in ln.lower())]
        # Look for FAIL on the API-version-match line specifically
        version_fail = [ln for ln in version_lines if "FAIL" in ln]
        assert version_fail, (
            f"Expected FAIL for API 4.1 vs project 4.10 (substring should NOT match);\n"
            f"Version-related lines: {version_lines}\nFull report:\n{output}"
        )

    def test_api_46_vs_project_46_is_ok(self, tmp_path_factory, monkeypatch):
        """API dump version 4.6 must match project features '4.6'."""
        proj = tmp_path_factory.mktemp("doctor_46match")
        (proj / "project.godot").write_text(
            '[gd_resource]\n[application]\nconfig/name="T"\n'
            'config/features=PackedStringArray("4.6", "Forward Plus")\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(config, "PROJECT_ROOT", proj)
        _clean_profile(monkeypatch, proj)

        data_dir = tmp_path_factory.mktemp("data_46")
        _make_api_dump(data_dir, major=4, minor=6, patch=2)
        (data_dir / "validate_script.gd").write_text("# harness\n", encoding="utf-8")
        monkeypatch.setattr(config, "DATA_DIR", data_dir)
        monkeypatch.setattr(config, "EXTENSION_API", data_dir / "extension_api.json")

        from godot_mcp import doctor
        output = doctor.report()
        lines = output.splitlines()
        version_fail = [
            ln for ln in lines
            if "FAIL" in ln and "version" in ln.lower() and "match" in ln.lower()
        ]
        assert not version_fail, (
            f"Unexpected version-match FAIL for matching 4.6 versions:\n{output}"
        )

    def test_api_41_version_string_parsing(self):
        """Unit-test the version comparison logic directly — not just through doctor."""
        # Import the helper we expect to find in doctor
        from godot_mcp.doctor import _version_matches
        # 4.1 must NOT match 4.10 (old substring would say True). The 4.10 token
        # is quoted as it always is in a real PackedStringArray, so it genuinely
        # enters the token list and the comparison must reject it on its merits.
        assert not _version_matches("4.1", '"4.10", "Forward Plus"'), (
            "_version_matches('4.1', '4.10, ...') must be False (substring false-positive bug)"
        )
        # 4.1 must match 4.1
        assert _version_matches("4.1", '"4.1", "Forward Plus"'), (
            "_version_matches('4.1', '4.1, ...') must be True"
        )
        # 4.6 must match 4.6
        assert _version_matches("4.6", '"4.6", "Forward Plus"'), (
            "_version_matches('4.6', '4.6, ...') must be True"
        )
        # 4.6 must NOT match 4.60 (hypothetical)
        assert not _version_matches("4.6", '"4.60", "Forward Plus"'), (
            "_version_matches('4.6', '4.60, ...') must be False"
        )


# ---------------------------------------------------------------------------
# C23: (relpath, mtime) fingerprint — rename detection
# ---------------------------------------------------------------------------

class TestFingerprintRenameDetection:
    """project_classes() must detect a rename even when file count and mtime-sum are preserved."""

    @pytest.fixture()
    def tmp_project(self, tmp_path_factory, monkeypatch):
        proj = tmp_path_factory.mktemp("classes_rename")
        (proj / "project.godot").write_text(
            '[gd_resource]\n[application]\nconfig/name="T"\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(config, "PROJECT_ROOT", proj)
        return proj

    def test_rename_detected_by_classes(self, tmp_project, monkeypatch):
        """Renaming a class_name file (same count, pinned mtime so mtime-sum is
        identical) → project_classes() returns the new path. The cache is NOT
        cleared between calls: the (relpath, mtime) fingerprint must invalidate
        it on its own. The old (count, mtime_sum) fingerprint would cache-hit
        here and return the stale path — so this test guards that regression."""
        from godot_mcp import project_ground

        project_ground._classes_cache = None

        old_file = tmp_project / "hero.gd"
        old_file.write_text("class_name Hero\nextends Node\n", encoding="utf-8")
        old_mtime = old_file.stat().st_mtime

        result1 = project_ground.classes()
        assert "res://hero.gd" in result1, f"hero.gd not in initial result: {result1}"

        # Rename: same content + same file count (1→1), and pin the new file's
        # mtime to the old one so (count, mtime_sum) is byte-for-byte identical.
        # Only the relpath differs — exactly the collision the old fingerprint missed.
        content = old_file.read_text(encoding="utf-8")
        old_file.unlink()
        new_file = tmp_project / "hero_renamed.gd"
        new_file.write_text(content, encoding="utf-8")
        os.utime(new_file, (old_mtime, old_mtime))

        # Deliberately do NOT reset the cache here.
        result2 = project_ground.classes()
        assert "res://hero_renamed.gd" in result2, (
            f"New path not in result after rename (stale cache?):\n{result2}"
        )
        assert "res://hero.gd" not in result2, (
            f"Old path res://hero.gd still in result after rename:\n{result2}"
        )

    def test_cache_hits_on_no_change(self, tmp_project, monkeypatch):
        """project_classes() must use cache when nothing changed."""
        from godot_mcp import project_ground

        project_ground._classes_cache = None
        (tmp_project / "foo.gd").write_text(
            "class_name Foo\nextends Node\n", encoding="utf-8"
        )

        result1 = project_ground.classes()
        # Second call — with no changes, must return exact same string from cache
        result2 = project_ground.classes()
        assert result1 == result2

    def test_valid_keys_rename_detected(self, tmp_project, monkeypatch):
        """catalogs.valid_keys() must re-scan when a file is swapped for one with
        a different name AND a different registered key, but the same file count
        and a pinned-identical mtime-sum — the exact collision the old
        (count, mtime_sum) fingerprint missed. The cache is NOT cleared between
        calls; the fingerprint alone must invalidate it. Output (the key set)
        differs, so a stale cache would visibly fail this test."""
        from godot_mcp import catalogs

        catalogs._valid_cache.clear()
        pattern = r'register\("(\w+)"\)'

        old_file = tmp_project / "reg_a.gd"
        old_file.write_text('func _ready():\n\tregister("TypeA")\n', encoding="utf-8")
        old_mtime = old_file.stat().st_mtime

        keys1 = catalogs.valid_keys(pattern)
        assert "TypeA" in keys1

        # Swap: same file count (1→1), pinned-identical mtime, but a different
        # name and a different key. Old fingerprint can't tell these two apart.
        old_file.unlink()
        new_file = tmp_project / "reg_b.gd"
        new_file.write_text('func _ready():\n\tregister("TypeB")\n', encoding="utf-8")
        os.utime(new_file, (old_mtime, old_mtime))

        # Deliberately do NOT clear the cache here.
        keys2 = catalogs.valid_keys(pattern)
        assert "TypeB" in keys2, f"rename not detected — stale cache returned {keys2}"
        assert "TypeA" not in keys2, f"stale key TypeA survived the rename: {keys2}"


# ---------------------------------------------------------------------------
# C23: _gd_signature deduplication check
# ---------------------------------------------------------------------------

class TestGdSignatureSharedHelper:
    """Both project_ground and catalogs must use the same _gd_signature helper."""

    def test_shared_helper_imported_from_shared_module(self):
        """After dedup, both modules should use the same function object."""
        from godot_mcp import catalogs, project_ground

        # Both must produce the same signature for the same directory
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "a.gd").write_text("extends Node\n", encoding="utf-8")

            import godot_mcp.config as cfg
            old_root = cfg.PROJECT_ROOT
            cfg.PROJECT_ROOT = tmp
            try:
                sig_pg = project_ground._gd_signature()
                sig_cat = catalogs._gd_signature()
            finally:
                cfg.PROJECT_ROOT = old_root

        assert sig_pg == sig_cat, (
            f"project_ground._gd_signature() {sig_pg!r} != "
            f"catalogs._gd_signature() {sig_cat!r}"
        )

    def test_signature_is_frozenset_of_pairs(self):
        """The new fingerprint must be a frozenset of (relpath, mtime) pairs, not (int, float)."""
        from godot_mcp import project_ground

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "test.gd").write_text("extends Node\n", encoding="utf-8")

            import godot_mcp.config as cfg
            old_root = cfg.PROJECT_ROOT
            cfg.PROJECT_ROOT = tmp
            try:
                sig = project_ground._gd_signature()
            finally:
                cfg.PROJECT_ROOT = old_root

        # Must be a frozenset (or set) — not (int, float)
        assert isinstance(sig, (frozenset, set)), (
            f"Expected frozenset/set fingerprint, got {type(sig)}: {sig!r}"
        )
        # Each element must be a 2-tuple
        for elem in sig:
            assert isinstance(elem, tuple) and len(elem) == 2, (
                f"Expected (relpath, mtime) pair, got {elem!r}"
            )
