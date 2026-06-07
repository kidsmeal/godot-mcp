"""Phase 3 tests: profile robustness (F-6, F-7).

All tests are fully offline — no Godot binary needed.

Coverage:
  1. Malformed TOML → Profile.errors non-empty, server still gets usable defaults (no raise).
  2. [[catalog]] entry missing 'pattern' → errors recorded; catalog(), build_catalog_refs(),
     valid_keys() do NOT raise.
  3. doctor.report() with a profile carrying errors → output contains FAIL + error text
     and NOT "All good.".
  4. Valid profile → errors empty, no spurious doctor FAIL.
  5. Existing Profile(...) constructions remain valid (errors field has a default).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from godot_mcp import config
from godot_mcp.profile import Profile, load

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_project(tmp_path: Path, toml_content: str | None = None) -> Path:
    """Write a minimal project dir: project.godot + optional godot-mcp.toml."""
    (tmp_path / "project.godot").write_text(
        '[application]\nconfig/name="TestProj"\n', encoding="utf-8"
    )
    if toml_content is not None:
        (tmp_path / "godot-mcp.toml").write_text(toml_content, encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# 1. Malformed TOML
# ---------------------------------------------------------------------------

class TestMalformedToml:
    def test_broken_toml_returns_errors(self, tmp_path):
        """A syntactically-broken godot-mcp.toml must populate Profile.errors."""
        proj = _make_project(tmp_path, toml_content="[unclosed\nkey = ")
        prof = load(proj)
        assert isinstance(prof.errors, list)
        assert len(prof.errors) > 0, "Expected at least one error for malformed TOML"

    def test_broken_toml_error_mentions_parse_failure(self, tmp_path):
        """The error string must contain something indicating a parse/TOML failure."""
        proj = _make_project(tmp_path, toml_content="[unclosed\nkey = ")
        prof = load(proj)
        combined = " ".join(prof.errors).lower()
        assert "parse" in combined or "toml" in combined or "error" in combined, (
            f"Error text should mention parse/TOML failure; got: {prof.errors}"
        )

    def test_broken_toml_still_returns_profile(self, tmp_path):
        """load() must return a Profile (not raise) even for a broken TOML."""
        proj = _make_project(tmp_path, toml_content="{{{{ completely invalid }")
        prof = load(proj)
        assert isinstance(prof, Profile)

    def test_broken_toml_falls_back_to_safe_defaults(self, tmp_path):
        """A broken TOML must still produce usable default values (name, godot_bin)."""
        proj = _make_project(tmp_path, toml_content="[unclosed\n")
        prof = load(proj)
        # name falls back to project name or "Godot project"
        assert isinstance(prof.name, str) and prof.name
        # godot_bin falls back to "godot" (or GODOT_BIN env override)
        assert isinstance(prof.godot_bin, str) and prof.godot_bin
        # catalogs/catalog_refs are empty lists (safe defaults)
        assert prof.catalogs == []
        assert prof.catalog_refs == []

    def test_no_file_produces_empty_errors(self, tmp_path):
        """When no godot-mcp.toml exists at all, errors must be empty (not an error)."""
        proj = _make_project(tmp_path, toml_content=None)  # no toml written
        prof = load(proj)
        assert prof.errors == [], f"No-file case must not produce errors; got: {prof.errors}"


# ---------------------------------------------------------------------------
# 2. Missing required keys in [[catalog]] / [[lint_catalog_ref]]
# ---------------------------------------------------------------------------

class TestSchemaValidation:
    def test_catalog_missing_pattern_records_error(self, tmp_path):
        """A [[catalog]] entry missing 'pattern' must produce an error in Profile.errors."""
        toml = '[project]\nname = "T"\n[[catalog]]\nname = "items"\nfile = "items.gd"\n'
        proj = _make_project(tmp_path, toml_content=toml)
        prof = load(proj)
        assert len(prof.errors) > 0, "Expected error for catalog missing 'pattern'"
        combined = " ".join(prof.errors)
        assert "pattern" in combined.lower() or "catalog" in combined.lower(), (
            f"Error should mention 'pattern' or 'catalog'; got: {prof.errors}"
        )

    def test_catalog_missing_name_records_error(self, tmp_path):
        """A [[catalog]] entry missing 'name' must produce an error."""
        toml = '[[catalog]]\nfile = "items.gd"\npattern = "r"\n'
        proj = _make_project(tmp_path, toml_content=toml)
        prof = load(proj)
        assert len(prof.errors) > 0

    def test_catalog_missing_file_records_error(self, tmp_path):
        """A [[catalog]] entry missing 'file' must produce an error."""
        toml = '[[catalog]]\nname = "items"\npattern = "r"\n'
        proj = _make_project(tmp_path, toml_content=toml)
        prof = load(proj)
        assert len(prof.errors) > 0

    def test_lint_catalog_ref_missing_valid_pattern_records_error(self, tmp_path):
        """A [[lint_catalog_ref]] entry missing 'valid_pattern' must produce an error."""
        toml = '[[lint_catalog_ref]]\nuse_pattern = "r"\n'
        proj = _make_project(tmp_path, toml_content=toml)
        prof = load(proj)
        assert len(prof.errors) > 0
        combined = " ".join(prof.errors)
        assert "valid_pattern" in combined or "lint_catalog_ref" in combined.lower(), (
            f"Error should mention missing key; got: {prof.errors}"
        )

    def test_lint_catalog_ref_missing_use_pattern_records_error(self, tmp_path):
        """A [[lint_catalog_ref]] entry missing 'use_pattern' must produce an error."""
        toml = '[[lint_catalog_ref]]\nvalid_pattern = "r"\n'
        proj = _make_project(tmp_path, toml_content=toml)
        prof = load(proj)
        assert len(prof.errors) > 0

    def test_valid_profile_no_errors(self, tmp_path):
        """A fully-valid profile with all required keys produces no errors."""
        toml = (
            '[project]\nname = "T"\n'
            '[[catalog]]\nname = "scenes"\nfile = "project.godot"\npattern = "(.*)"\n'
            '[[lint_catalog_ref]]\nuse_pattern = "u"\nvalid_pattern = "v"\n'
        )
        proj = _make_project(tmp_path, toml_content=toml)
        prof = load(proj)
        assert prof.errors == [], f"Valid profile must have no errors; got: {prof.errors}"

    def test_error_mentions_entry_index(self, tmp_path):
        """Error messages for bad specs should identify WHICH entry has the problem."""
        toml = '[[catalog]]\nname = "items"\nfile = "items.gd"\n'  # missing pattern
        proj = _make_project(tmp_path, toml_content=toml)
        prof = load(proj)
        combined = " ".join(prof.errors)
        # Should mention the index (0) or the entry name "items"
        assert "0" in combined or "items" in combined.lower(), (
            f"Error should identify offending entry; got: {prof.errors}"
        )


# ---------------------------------------------------------------------------
# 3. Catalog functions are crash-proof with bad specs
# ---------------------------------------------------------------------------

class TestCatalogCrashProof:
    """catalog(), build_catalog_refs(), and valid_keys() must never raise on a bad spec."""

    @pytest.fixture()
    def bad_catalog_profile(self, tmp_path, monkeypatch):
        """A Profile with a catalog spec missing 'pattern', pointed at a tmp project."""
        toml = '[[catalog]]\nname = "items"\nfile = "project.godot"\n'
        proj = _make_project(tmp_path, toml_content=toml)
        prof = load(proj)
        monkeypatch.setattr(config, "PROJECT_ROOT", proj)
        monkeypatch.setattr(config, "PROFILE", prof)
        return prof

    @pytest.fixture()
    def bad_ref_profile(self, tmp_path, monkeypatch):
        """A Profile with a lint_catalog_ref spec missing 'valid_pattern'."""
        toml = '[[lint_catalog_ref]]\nuse_pattern = "r"\n'
        proj = _make_project(tmp_path, toml_content=toml)
        prof = load(proj)
        monkeypatch.setattr(config, "PROJECT_ROOT", proj)
        monkeypatch.setattr(config, "PROFILE", prof)
        return prof

    def test_catalog_all_does_not_raise(self, bad_catalog_profile):
        from godot_mcp import catalogs
        result = catalogs.catalog("all")
        assert isinstance(result, str)

    def test_catalog_named_does_not_raise(self, bad_catalog_profile):
        from godot_mcp import catalogs
        result = catalogs.catalog("items")
        assert isinstance(result, str)

    @pytest.fixture()
    def nameless_catalog_profile(self, tmp_path, monkeypatch):
        """A Profile with a catalog spec missing 'name' (and 'pattern')."""
        toml = '[[catalog]]\nfile = "project.godot"\npattern = "x"\n'
        proj = _make_project(tmp_path, toml_content=toml)
        prof = load(proj)
        monkeypatch.setattr(config, "PROJECT_ROOT", proj)
        monkeypatch.setattr(config, "PROFILE", prof)
        return prof

    def test_catalog_unknown_kind_does_not_raise(self, nameless_catalog_profile):
        """The 'Unknown catalog' fallback builds the available-list from PROFILE.catalogs;
        a nameless (invalid) spec must not raise KeyError there."""
        from godot_mcp import catalogs
        result = catalogs.catalog("does-not-exist")
        assert isinstance(result, str)
        assert "Unknown catalog" in result

    def test_build_catalog_refs_does_not_raise(self, bad_ref_profile):
        from godot_mcp import catalogs
        result = catalogs.build_catalog_refs()
        assert isinstance(result, list)

    def test_valid_keys_does_not_raise(self):
        from godot_mcp import catalogs
        # valid_keys takes a pattern string directly — empty/bogus pattern must not raise
        result = catalogs.valid_keys("")
        assert isinstance(result, set)


# ---------------------------------------------------------------------------
# 4. doctor.report surfaces profile errors as FAIL
# ---------------------------------------------------------------------------

class TestDoctorProfileErrors:
    """doctor.report() must surface Profile.errors as FAIL lines."""

    @pytest.fixture()
    def _stub_profile_with_errors(self, monkeypatch, tmp_path):
        """Monkeypatch config.PROFILE to a Profile with errors, project root to tmp_path
        (with a project.godot so the project-root check passes)."""
        (tmp_path / "project.godot").write_text("[gd_resource]\n", encoding="utf-8")
        monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
        prof = Profile(
            name="BrokenProj",
            errors=["TOML parse error: expected a value at line 2 col 1"],
        )
        monkeypatch.setattr(config, "PROFILE", prof)
        return prof

    @pytest.fixture()
    def _stub_valid_profile(self, monkeypatch, tmp_path):
        """Monkeypatch config.PROFILE to a clean Profile with no errors."""
        (tmp_path / "project.godot").write_text("[gd_resource]\n", encoding="utf-8")
        monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
        prof = Profile(name="CleanProj")
        monkeypatch.setattr(config, "PROFILE", prof)
        return prof

    def test_report_contains_fail_when_errors(self, _stub_profile_with_errors):
        from godot_mcp import doctor
        output = doctor.report()
        assert "FAIL" in output, f"Expected FAIL in report; got:\n{output}"

    def test_report_contains_error_text(self, _stub_profile_with_errors):
        from godot_mcp import doctor
        output = doctor.report()
        assert "TOML parse error" in output or "parse error" in output.lower(), (
            f"Expected error text in report; got:\n{output}"
        )

    def test_report_not_all_good_when_errors(self, _stub_profile_with_errors):
        from godot_mcp import doctor
        output = doctor.report()
        assert "All good." not in output, (
            f"'All good.' must NOT appear when profile has errors; got:\n{output}"
        )

    def test_report_no_profile_error_fail_when_no_errors(self, _stub_valid_profile):
        from godot_mcp import doctor
        output = doctor.report()
        # No FAIL line should mention "profile error" for a clean profile.
        # (Other doctor checks may fail for a minimal tmp project — we only assert
        # on the absence of a profile-error FAIL line.)
        lines = output.splitlines()
        profile_fail_lines = [
            ln for ln in lines if "FAIL" in ln and "profile error" in ln.lower()
        ]
        assert profile_fail_lines == [], (
            f"No 'profile error' FAIL should appear for a clean profile; got: {profile_fail_lines}"
        )

    def test_report_no_spurious_fail_for_valid_profile(self, _stub_valid_profile):
        from godot_mcp import doctor
        output = doctor.report()
        # Count FAIL lines — should be zero for a minimal clean project
        # (project.godot exists, but godot binary / API dump may be absent on CI)
        # We only assert on profile-error FAIL, so just check "profile error" FAIL absent
        lines = output.splitlines()
        profile_error_fail_lines = [
            ln for ln in lines
            if "FAIL" in ln and ("profile" in ln.lower() or "error" in ln.lower() or "parse" in ln.lower())
        ]
        assert profile_error_fail_lines == [], (
            f"No profile-error FAIL should appear for a valid profile; got: {profile_error_fail_lines}"
        )

    def test_multiple_errors_each_produce_fail_line(self, monkeypatch, tmp_path):
        """Each error in Profile.errors must produce its own FAIL line."""
        (tmp_path / "project.godot").write_text("[gd_resource]\n", encoding="utf-8")
        monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
        prof = Profile(
            name="MultiErr",
            errors=[
                "TOML parse error: line 3",
                "catalog[0] missing key: pattern",
            ],
        )
        monkeypatch.setattr(config, "PROFILE", prof)
        from godot_mcp import doctor
        output = doctor.report()
        assert output.count("FAIL") >= 2, (
            f"Expected at least 2 FAIL lines for 2 errors; got:\n{output}"
        )

    def test_issue_count_reflects_profile_errors(self, monkeypatch, tmp_path):
        """The issue count in the header must include profile errors."""
        (tmp_path / "project.godot").write_text("[gd_resource]\n", encoding="utf-8")
        monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
        prof = Profile(
            name="ErrProj",
            errors=["TOML parse error: something"],
        )
        monkeypatch.setattr(config, "PROFILE", prof)
        from godot_mcp import doctor
        output = doctor.report()
        # Must say N issue(s) found, not "All good."
        assert "issue" in output and "All good." not in output


# ---------------------------------------------------------------------------
# 5. Backward compatibility: Profile() without errors stays valid
# ---------------------------------------------------------------------------

class TestProfileBackwardCompat:
    def test_profile_no_errors_arg_defaults_to_empty(self):
        """Profile(name='x') must work — errors is optional with default []."""
        prof = Profile(name="MyProj")
        assert prof.errors == []

    def test_profile_explicit_errors_works(self):
        """Profile with explicit errors list must store them."""
        prof = Profile(name="X", errors=["an error"])
        assert prof.errors == ["an error"]

    def test_profile_positional_construction_still_valid(self):
        """Existing code passing positional/keyword args must not break."""
        prof = Profile(
            name="P",
            godot_bin="godot4",
            suite_scene=None,
            integration_scene=None,
            docs={},
            catalogs=[],
            catalog_refs=[],
        )
        assert prof.errors == []
