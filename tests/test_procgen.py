"""Phase 0 (procgen tool suite): offline tests for the procgen harness probe.

All tests monkeypatch runner.run_temp_probe — no real Godot binary required.
"""
from __future__ import annotations

from godot_mcp import procgen


class TestPingParsesSentinelJson:
    def test_ping_parses_engine_version(self, monkeypatch):
        canned = (
            "Godot Engine v4.6.2.stable\n"
            "PROCGEN_JSON_BEGIN\n"
            '{"engine_version":"4.6.2.stable","ok":true}\n'
            "PROCGEN_JSON_END\n"
        )
        monkeypatch.setattr(
            procgen.runner,
            "run_temp_probe",
            lambda source, timeout=30: {"rc": 0, "out": canned, "err": "", "timeout": False},
        )
        result = procgen.ping()
        assert "4.6.2.stable" in result
        assert "procgen harness OK" in result

    def test_ping_extracts_multiline_json_between_sentinels(self, monkeypatch):
        """The sentinel scan must tolerate stray engine boot noise around the block."""
        canned = (
            "Godot Engine v4.6.2.stable - Rendering ...\n"
            "some boot warning\n"
            "PROCGEN_JSON_BEGIN\n"
            '{"engine_version":"4.6.2.stable","ok":true}\n'
            "PROCGEN_JSON_END\n"
            "\n"
        )
        monkeypatch.setattr(
            procgen.runner,
            "run_temp_probe",
            lambda source, timeout=30: {"rc": 0, "out": canned, "err": "", "timeout": False},
        )
        result = procgen.ping()
        assert "4.6.2.stable" in result


class TestPingGracefulDegradation:
    def test_godot_unavailable_returns_unavailable_string(self, monkeypatch):
        monkeypatch.setattr(
            procgen.runner,
            "run_temp_probe",
            lambda source, timeout=30: {
                "rc": None,
                "out": "",
                "err": "Godot binary not found (godot). Set GODOT_BIN to the .exe.",
                "timeout": False,
            },
        )
        result = procgen.ping()
        assert "UNAVAILABLE" in result
        assert "Godot binary not found" in result

    def test_timeout_returns_unavailable_string(self, monkeypatch):
        monkeypatch.setattr(
            procgen.runner,
            "run_temp_probe",
            lambda source, timeout=30: {"rc": None, "out": "", "err": "", "timeout": True},
        )
        result = procgen.ping()
        assert "UNAVAILABLE" in result
        assert "timed out" in result.lower()

    def test_missing_sentinel_returns_unavailable_string(self, monkeypatch):
        """rc == 0 but no PROCGEN_JSON markers (e.g. a crash before print) must
        degrade gracefully rather than raising."""
        monkeypatch.setattr(
            procgen.runner,
            "run_temp_probe",
            lambda source, timeout=30: {"rc": 0, "out": "Godot Engine v4.6.2\n", "err": "", "timeout": False},
        )
        result = procgen.ping()
        assert "UNAVAILABLE" in result

    def test_malformed_json_returns_unavailable_string(self, monkeypatch):
        canned = "PROCGEN_JSON_BEGIN\n{not valid json\nPROCGEN_JSON_END\n"
        monkeypatch.setattr(
            procgen.runner,
            "run_temp_probe",
            lambda source, timeout=30: {"rc": 0, "out": canned, "err": "", "timeout": False},
        )
        result = procgen.ping()
        assert "UNAVAILABLE" in result
        assert "malformed JSON" in result


class TestPingComposesSceneTreeScript:
    def test_probe_source_extends_scenetree(self, monkeypatch):
        """The composed script must extend SceneTree so run_temp_probe's headless
        --script invocation doesn't need the GUI-dialog guard runner.run_script has."""
        captured: list[str] = []

        def spy(source, timeout=30):
            captured.append(source)
            return {"rc": 0, "out": "PROCGEN_JSON_BEGIN\n{}\nPROCGEN_JSON_END\n", "err": "", "timeout": False}

        monkeypatch.setattr(procgen.runner, "run_temp_probe", spy)
        procgen.ping()
        assert captured
        assert captured[0].lstrip().startswith("extends SceneTree")
        assert "quit(" in captured[0]
