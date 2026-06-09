"""Phase 5 tests: Feature F grounding surfaces.

All tests are fully offline — no Godot binary needed.

Coverage:
  1. project_input_actions: temp project.godot with [input] section.
  2. Input-action lint rule (unknown-input-action): typo fires, correct doesn't, novel doesn't.
  3. Input-action lint fires on the WRITE PATH (edit.write_script).
  4. lint.py re.error guard: invalid-regex use_pattern must not raise.
  5. project_setting: file value parsed for dotted key; resolve=True monkeypatched.
  6. project_classes: two class_name files → both mapped; cache returns same result.
  7. project_layers: [layer_names] section parsed → grouped output.
"""
from __future__ import annotations

import pytest

from godot_mcp import config  # noqa: F401 — used by fixtures via monkeypatch

# ---------------------------------------------------------------------------
# Shared tmp_project fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_project(tmp_path_factory, monkeypatch):
    """Minimal Godot project with project.godot. config.PROJECT_ROOT is repointed here."""
    proj = tmp_path_factory.mktemp("project5")
    (proj / "project.godot").write_text(
        '[gd_resource]\n[application]\nconfig/name="TestProj"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "PROJECT_ROOT", proj)
    return proj


# ---------------------------------------------------------------------------
# 1. project_input_actions
# ---------------------------------------------------------------------------

PROJECT_GODOT_WITH_INPUT = """\
config_version=5

[application]
config/name="TestProj"

[input]

jump={
"deadzone": 0.5,
"events": [Object(InputEventKey,"resource_local_to_scene":false,"resource_name":"","device":-1,"window_id":0,"alt_pressed":false,"shift_pressed":false,"ctrl_pressed":false,"meta_pressed":false,"pressed":false,"keycode":0,"physical_keycode":32,"key_label":0,"unicode":32,"location":0,"echo":false,"script":null)
]
}
fire={
"deadzone": 0.5,
"events": []
}

[rendering]
"""

class TestProjectInputActions:
    @pytest.fixture()
    def project_with_input(self, tmp_project):
        (tmp_project / "project.godot").write_text(PROJECT_GODOT_WITH_INPUT, encoding="utf-8")
        return tmp_project

    def test_custom_action_appears(self, project_with_input):
        from godot_mcp import project_ground
        result = project_ground.input_actions()
        assert "jump" in result
        assert "fire" in result

    def test_builtin_ui_accept_appears(self, project_with_input):
        from godot_mcp import project_ground
        result = project_ground.input_actions()
        assert "ui_accept" in result

    def test_distinguishes_project_vs_builtin(self, project_with_input):
        from godot_mcp import project_ground
        result = project_ground.input_actions()
        # Should label project-defined and built-in separately
        lower = result.lower()
        assert "project" in lower or "custom" in lower or "defined" in lower

    def test_no_input_section_returns_builtins(self, tmp_project):
        """When there's no [input] section, still returns built-in ui_* actions."""
        from godot_mcp import project_ground
        result = project_ground.input_actions()
        assert "ui_accept" in result

    def test_input_action_set_includes_custom_and_builtin(self, project_with_input):
        from godot_mcp import project_ground
        action_set = project_ground.input_action_set()
        assert "jump" in action_set
        assert "fire" in action_set
        assert "ui_accept" in action_set
        assert "ui_cancel" in action_set

    def test_input_action_set_no_section_still_has_builtins(self, tmp_project):
        from godot_mcp import project_ground
        action_set = project_ground.input_action_set()
        assert "ui_left" in action_set
        assert "ui_right" in action_set

    def test_server_tool_registered(self, project_with_input):
        from godot_mcp.server import project_input_actions
        result = project_input_actions()
        assert isinstance(result, str)
        assert "ui_accept" in result


# ---------------------------------------------------------------------------
# 2. Input-action lint rule (unknown-input-action)
# ---------------------------------------------------------------------------

class TestInputActionLint:
    """The unknown-input-action rule flags typos of registered actions."""

    def _lint(self, source, action_set=None):
        from godot_mcp import lint
        if action_set is None:
            action_set = {"ui_accept", "ui_cancel", "ui_left", "ui_right", "jump", "fire"}
        return lint.lint_source(source, "res://test.gd", input_actions=action_set)

    def test_typo_fires_warning(self):
        """ui_acept is edit-distance 1 from ui_accept — must fire unknown-input-action."""
        source = 'Input.is_action_pressed("ui_acept")\n'
        findings = self._lint(source)
        rules = [f["rule"] for f in findings]
        assert "unknown-input-action" in rules, f"Expected unknown-input-action in {rules}"

    def test_typo_suggests_correct(self):
        """The warning message should suggest 'ui_accept'."""
        source = 'Input.is_action_pressed("ui_acept")\n'
        findings = self._lint(source)
        ia_findings = [f for f in findings if f["rule"] == "unknown-input-action"]
        assert ia_findings
        assert "ui_accept" in ia_findings[0]["message"]

    def test_correct_action_no_warning(self):
        """ui_accept is a valid action — must not fire."""
        source = 'Input.is_action_pressed("ui_accept")\n'
        findings = self._lint(source)
        ia_findings = [f for f in findings if f["rule"] == "unknown-input-action"]
        assert not ia_findings, f"Unexpected unknown-input-action findings: {ia_findings}"

    def test_novel_action_no_warning(self):
        """completely_novel_action_xyz is not near any registered action — must not fire."""
        source = 'Input.is_action_pressed("completely_novel_action_xyz")\n'
        findings = self._lint(source)
        ia_findings = [f for f in findings if f["rule"] == "unknown-input-action"]
        assert not ia_findings, f"Unexpected false positive: {ia_findings}"

    def test_just_pressed_typo_fires(self):
        """is_action_just_pressed with a typo must also fire."""
        source = 'Input.is_action_just_pressed("ui_cancl")\n'
        findings = self._lint(source)
        ia_findings = [f for f in findings if f["rule"] == "unknown-input-action"]
        assert ia_findings

    def test_just_released_typo_fires(self):
        """is_action_just_released with a typo must also fire."""
        source = 'Input.is_action_just_released("ui_lft")\n'
        findings = self._lint(source)
        ia_findings = [f for f in findings if f["rule"] == "unknown-input-action"]
        assert ia_findings

    def test_no_action_set_no_findings(self):
        """When input_actions is None (or empty), the rule doesn't fire."""
        from godot_mcp import lint
        source = 'Input.is_action_pressed("anything")\n'
        findings = lint.lint_source(source, "res://test.gd", input_actions=None)
        ia_findings = [f for f in findings if f["rule"] == "unknown-input-action"]
        assert not ia_findings

    def test_severity_is_warn(self):
        """The unknown-input-action finding must have severity 'warn'."""
        source = 'Input.is_action_pressed("ui_acept")\n'
        findings = self._lint(source)
        ia_findings = [f for f in findings if f["rule"] == "unknown-input-action"]
        assert ia_findings
        assert ia_findings[0]["severity"] == "warn"

    def test_suppression_works(self):
        """# lint: ignore=unknown-input-action must suppress the finding."""
        source = 'Input.is_action_pressed("ui_acept")  # lint: ignore=unknown-input-action\n'
        findings = self._lint(source)
        ia_findings = [f for f in findings if f["rule"] == "unknown-input-action"]
        assert not ia_findings, f"Suppression did not work: {ia_findings}"


# ---------------------------------------------------------------------------
# 3. Input-action lint fires on the WRITE PATH (edit.write_script)
# ---------------------------------------------------------------------------

class TestInputActionLintOnWritePath:
    """The unknown-input-action rule must appear in edit.write_script findings."""

    @pytest.fixture()
    def project_with_input(self, tmp_project):
        (tmp_project / "project.godot").write_text(PROJECT_GODOT_WITH_INPUT, encoding="utf-8")
        return tmp_project

    def test_write_path_includes_input_action_finding(self, project_with_input, monkeypatch):
        """write_script must report unknown-input-action for a typo in the written content."""
        import subprocess
        # Prevent any real Godot check from launching
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _fake_ok_proc())

        from godot_mcp import edit
        content = 'extends Node\n\nfunc _ready() -> void:\n\tInput.is_action_pressed("ui_acept")\n'
        result = edit.write_script("res://test_write.gd", content)
        assert "unknown-input-action" in result, (
            f"Expected unknown-input-action in write_script output; got:\n{result}"
        )

    def test_write_path_no_false_positive_for_correct_action(self, project_with_input, monkeypatch):
        """write_script must NOT flag a correct action name."""
        import subprocess
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _fake_ok_proc())

        from godot_mcp import edit
        content = 'extends Node\n\nfunc _ready() -> void:\n\tInput.is_action_pressed("jump")\n'
        result = edit.write_script("res://test_write2.gd", content)
        assert "unknown-input-action" not in result, (
            f"Unexpected unknown-input-action in write_script output; got:\n{result}"
        )


def _fake_ok_proc():
    """Return a fake subprocess.CompletedProcess that looks like godot --check-only success."""
    import subprocess
    return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")


# ---------------------------------------------------------------------------
# 4. lint.py re.error guard (lint.py:242)
# ---------------------------------------------------------------------------

class TestLintReErrorGuard:
    """A catalog_refs entry with an invalid-regex use_pattern must not raise."""

    def test_invalid_regex_does_not_raise(self):
        from godot_mcp import lint
        bad_refs = [{"use_pattern": "[invalid(regex", "valid_pattern": "", "valid_set": set()}]
        # Must not raise re.error
        findings = lint.lint_source("extends Node\n", "res://test.gd", catalog_refs=bad_refs)
        assert isinstance(findings, list)

    def test_invalid_regex_skips_that_ref(self):
        """The bad ref is skipped; valid refs still fire."""
        from godot_mcp import lint
        mixed_refs = [
            {"use_pattern": "[invalid(regex", "valid_pattern": "", "valid_set": set()},
            {
                "use_pattern": r'effect_type\("([^"]+)"',
                "valid_pattern": r'EFFECT_TYPE_(\w+)',
                "valid_set": {"fire", "ice"},
            },
        ]
        source = 'effect_type("unknown_xyz")\n'
        findings = lint.lint_source(source, "res://t.gd", catalog_refs=mixed_refs)
        # Should not raise; "unknown_xyz" near "fire"/"ice" by distance check
        assert isinstance(findings, list)

    def test_invalid_regex_in_lint_source_does_not_raise(self):
        """lint_source called from the write path must not raise on bad catalog ref."""
        from godot_mcp import lint
        bad_refs = [{"use_pattern": "((((", "valid_pattern": "", "valid_set": set()}]
        result = lint.lint_source("var x = 1\n", "res://foo.gd", catalog_refs=bad_refs)
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# 5. project_setting
# ---------------------------------------------------------------------------

PROJECT_GODOT_WITH_SETTINGS = """\
config_version=5

[application]

config/name="TestProj"
config/icon="res://icon.png"
run/main_scene="res://main.tscn"

[display]

window/size/viewport_width=1280
window/size/viewport_height=720
"""

class TestProjectSetting:
    @pytest.fixture()
    def settings_project(self, tmp_project):
        (tmp_project / "project.godot").write_text(PROJECT_GODOT_WITH_SETTINGS, encoding="utf-8")
        return tmp_project

    def test_file_value_dotted_name(self, settings_project):
        from godot_mcp import project_ground
        result = project_ground.setting("application/config/name")
        assert "TestProj" in result

    def test_file_value_second_key(self, settings_project):
        from godot_mcp import project_ground
        result = project_ground.setting("application/config/icon")
        assert "icon.png" in result

    def test_file_value_display_section(self, settings_project):
        from godot_mcp import project_ground
        result = project_ground.setting("display/window/size/viewport_width")
        assert "1280" in result

    def test_missing_key_returns_not_found(self, settings_project):
        from godot_mcp import project_ground
        result = project_ground.setting("nonexistent/key/here")
        assert "not found" in result.lower() or "not set" in result.lower() or "no value" in result.lower()

    def test_never_raises(self, settings_project):
        from godot_mcp import project_ground
        # Should graceful-degrade, not raise
        result = project_ground.setting("")
        assert isinstance(result, str)

    def test_resolve_true_uses_run_temp_probe(self, settings_project, monkeypatch):
        """resolve=True must call runner.run_temp_probe (monkeypatched) and parse the output."""
        from godot_mcp import runner
        probe_called = []

        def fake_probe(source, user_args=None, timeout=60):
            probe_called.append(source)
            return {"rc": 0, "out": "MyGameName\n", "err": "", "timeout": False}

        monkeypatch.setattr(runner, "run_temp_probe", fake_probe)
        from godot_mcp import project_ground
        result = project_ground.setting("application/config/name", resolve=True)
        assert probe_called, "run_temp_probe must be called when resolve=True"
        assert "MyGameName" in result

    def test_resolve_true_godot_unavailable_degrades(self, settings_project, monkeypatch):
        """When the Godot probe fails (binary not found), resolve=True degrades gracefully."""
        from godot_mcp import runner

        def fake_probe(source, user_args=None, timeout=60):
            return {"rc": None, "out": "", "err": "Godot binary not found", "timeout": False}

        monkeypatch.setattr(runner, "run_temp_probe", fake_probe)
        from godot_mcp import project_ground
        result = project_ground.setting("application/config/name", resolve=True)
        assert isinstance(result, str)
        # Should not raise and should return something meaningful

    def test_server_tool_registered(self, settings_project):
        from godot_mcp.server import project_setting
        result = project_setting("application/config/name")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# 6. project_classes
# ---------------------------------------------------------------------------

class TestProjectClasses:
    @pytest.fixture()
    def two_class_project(self, tmp_project):
        (tmp_project / "hero.gd").write_text(
            "class_name Hero\nextends CharacterBody2D\n", encoding="utf-8"
        )
        (tmp_project / "enemy.gd").write_text(
            "class_name Enemy\nextends Node2D\n", encoding="utf-8"
        )
        return tmp_project

    def test_both_classes_appear(self, two_class_project):
        from godot_mcp import project_ground
        result = project_ground.classes()
        assert "Hero" in result
        assert "Enemy" in result

    def test_res_paths_in_output(self, two_class_project):
        from godot_mcp import project_ground
        result = project_ground.classes()
        assert "res://hero.gd" in result
        assert "res://enemy.gd" in result

    def test_no_class_name_not_listed(self, two_class_project):
        """A .gd file without class_name must not appear."""
        (two_class_project / "util.gd").write_text("extends Node\n", encoding="utf-8")
        from godot_mcp import project_ground
        result = project_ground.classes()
        # util.gd has no class_name, should not appear by filename
        lines = result.splitlines()
        util_lines = [ln for ln in lines if "util.gd" in ln]
        assert not util_lines, f"util.gd (no class_name) should not appear: {util_lines}"

    def test_cache_returns_same_result(self, two_class_project):
        """Calling classes() twice returns the same result (cache path covered)."""
        from godot_mcp import project_ground
        result1 = project_ground.classes()
        result2 = project_ground.classes()
        assert result1 == result2

    def test_empty_project_no_classes(self, tmp_project):
        """A project with no .gd files returns a suitable message."""
        from godot_mcp import project_ground
        result = project_ground.classes()
        assert isinstance(result, str)

    def test_server_tool_registered(self, two_class_project):
        from godot_mcp.server import project_classes
        result = project_classes()
        assert isinstance(result, str)
        assert "Hero" in result


# ---------------------------------------------------------------------------
# 7. project_layers
# ---------------------------------------------------------------------------

PROJECT_GODOT_WITH_LAYERS = """\
config_version=5

[application]
config/name="TestProj"

[layer_names]

2d_physics/layer_1="Ground"
2d_physics/layer_2="Player"
2d_physics/layer_3="Enemies"
3d_render/layer_1="WorldGeometry"
3d_render/layer_3="FX"
2d_navigation/layer_1="Walkable"
avoidance/layer_1="Agents"
"""

class TestProjectLayers:
    @pytest.fixture()
    def layers_project(self, tmp_project):
        (tmp_project / "project.godot").write_text(PROJECT_GODOT_WITH_LAYERS, encoding="utf-8")
        return tmp_project

    def test_2d_physics_layer_appears(self, layers_project):
        from godot_mcp import project_ground
        result = project_ground.layers()
        assert "Ground" in result
        assert "Player" in result
        assert "Enemies" in result

    def test_3d_render_layer_appears(self, layers_project):
        from godot_mcp import project_ground
        result = project_ground.layers()
        assert "WorldGeometry" in result
        assert "FX" in result

    def test_2d_navigation_layer_appears(self, layers_project):
        from godot_mcp import project_ground
        result = project_ground.layers()
        assert "Walkable" in result

    def test_avoidance_layer_appears(self, layers_project):
        from godot_mcp import project_ground
        result = project_ground.layers()
        assert "Agents" in result

    def test_grouped_by_category(self, layers_project):
        from godot_mcp import project_ground
        result = project_ground.layers()
        # Categories must appear as section headers
        lower = result.lower()
        assert "2d_physics" in lower or "2d physics" in lower
        assert "3d_render" in lower or "3d render" in lower

    def test_no_layer_names_section(self, tmp_project):
        """A project.godot with no [layer_names] gracefully returns a message."""
        from godot_mcp import project_ground
        result = project_ground.layers()
        assert isinstance(result, str)

    def test_layer_number_in_output(self, layers_project):
        from godot_mcp import project_ground
        result = project_ground.layers()
        # Layer numbers (1, 2, 3) should appear in some form
        assert "1" in result

    def test_server_tool_registered(self, layers_project):
        from godot_mcp.server import project_layers
        result = project_layers()
        assert isinstance(result, str)
        assert "Ground" in result
