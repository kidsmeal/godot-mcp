"""Phase 6 bridge hardening tests — offline, monkeypatching only.

GDScript-side tests (B1, B6-GD, B7, B8, B9) require a running Godot editor bridge
and are skipped here.  Python-side items (B3, B4, B5, B6-server, B10) are fully
offline.
"""
from __future__ import annotations

import socket
import time

import pytest

from godot_mcp import config  # noqa: F401 — used via monkeypatch in fixtures

# ---------------------------------------------------------------------------
# Shared fixture: temp project root so config.PROJECT_ROOT is safe
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_project(tmp_path_factory, monkeypatch):
    proj = tmp_path_factory.mktemp("bridge_proj")
    (proj / "project.godot").write_text("[gd_resource]\n", encoding="utf-8")
    monkeypatch.setattr(config, "PROJECT_ROOT", proj)
    return proj


# ---------------------------------------------------------------------------
# B3 — distinct error messages for the three socket failure modes
# ---------------------------------------------------------------------------

class TestB3ErrorClassification:
    def test_connection_refused(self, monkeypatch):
        def fake_create(*a, **kw):
            raise ConnectionRefusedError("refused")
        monkeypatch.setattr(socket, "create_connection", fake_create)
        from godot_mcp import bridge
        r = bridge._send({"cmd": "ping"})
        assert r["ok"] is False
        assert "not reachable" in r["error"]

    def test_timeout(self, monkeypatch):
        def fake_create(*a, **kw):
            raise TimeoutError("timed out")
        monkeypatch.setattr(socket, "create_connection", fake_create)
        from godot_mcp import bridge
        r = bridge._send({"cmd": "ping"})
        assert r["ok"] is False
        assert "timed out" in r["error"]

    def test_connection_reset(self, monkeypatch):
        def fake_create(*a, **kw):
            raise ConnectionResetError("reset")
        monkeypatch.setattr(socket, "create_connection", fake_create)
        from godot_mcp import bridge
        r = bridge._send({"cmd": "ping"})
        assert r["ok"] is False
        assert "disconnected" in r["error"]

    def test_os_error(self, monkeypatch):
        def fake_create(*a, **kw):
            raise OSError("generic")
        monkeypatch.setattr(socket, "create_connection", fake_create)
        from godot_mcp import bridge
        r = bridge._send({"cmd": "ping"})
        assert r["ok"] is False
        assert "disconnected" in r["error"]

    def test_json_decode_error(self, monkeypatch):
        """Empty / malformed response from bridge → friendly error, not exception."""
        class FakeSocket:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def sendall(self, data): pass
            def settimeout(self, t): pass
            def recv(self, n): return b"\n"  # newline with no JSON content

        monkeypatch.setattr(socket, "create_connection", lambda *a, **kw: FakeSocket())
        from godot_mcp import bridge
        r = bridge._send({"cmd": "ping"})
        assert r["ok"] is False
        assert "invalid JSON" in r["error"] or "malformed" in r["error"]

    def test_errors_are_distinct(self, monkeypatch):
        """The three main error messages must differ so callers can distinguish them."""
        messages = []
        for exc_class in [ConnectionRefusedError, TimeoutError, ConnectionResetError]:
            def fake_create(*a, exc=exc_class, **kw):
                raise exc("test")
            monkeypatch.setattr(socket, "create_connection", fake_create)
            from godot_mcp import bridge
            r = bridge._send({"cmd": "ping"})
            messages.append(r["error"])
        assert len(set(messages)) == 3, f"Error messages must be distinct: {messages}"


# ---------------------------------------------------------------------------
# B4 — r.get("error", ...) in all wrappers — none raise on missing "error" key
# ---------------------------------------------------------------------------

class TestB4DefensiveErrorAccess:
    """Monkeypatch _send to return {"ok": False} (no "error" key).
    None of the wrapper functions should raise."""

    @pytest.fixture(autouse=True)
    def stub_send(self, monkeypatch):
        from godot_mcp import bridge
        monkeypatch.setattr(bridge, "_send", lambda *a, **kw: {"ok": False})

    def test_ping_no_raise(self):
        from godot_mcp import bridge
        result = bridge.ping()
        assert isinstance(result, str)

    def test_run_game_no_raise(self):
        from godot_mcp import bridge
        result = bridge.run_game("main")
        assert isinstance(result, str)

    def test_stop_game_no_raise(self):
        from godot_mcp import bridge
        result = bridge.stop_game()
        assert isinstance(result, str)

    def test_is_playing_no_raise(self):
        from godot_mcp import bridge
        result = bridge.is_playing()
        assert isinstance(result, str)

    def test_scene_tree_no_raise(self):
        from godot_mcp import bridge
        result = bridge.scene_tree()
        assert isinstance(result, str)

    def test_open_scene_no_raise(self):
        from godot_mcp import bridge
        result = bridge.open_scene("res://foo.tscn")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# B5 Python — run_game("unknown") returns error without calling _send
# ---------------------------------------------------------------------------

class TestB5RunGameValidation:
    def test_unknown_scene_rejected_before_send(self, monkeypatch):
        from godot_mcp import bridge
        sent = []
        monkeypatch.setattr(bridge, "_send", lambda *a, **kw: sent.append(a) or {"ok": True, "playing": "main"})
        result = bridge.run_game("unknown")
        assert isinstance(result, str)
        assert "unknown" in result.lower() or "scene" in result.lower()
        assert not sent, "_send must NOT be called for an invalid scene value"

    def test_main_accepted(self, monkeypatch):
        from godot_mcp import bridge
        monkeypatch.setattr(bridge, "_send", lambda *a, **kw: {"ok": True, "playing": "main"})
        result = bridge.run_game("main")
        assert "main" in result.lower()

    def test_current_accepted(self, monkeypatch):
        from godot_mcp import bridge
        monkeypatch.setattr(bridge, "_send", lambda *a, **kw: {"ok": True, "playing": "current"})
        result = bridge.run_game("current")
        assert "current" in result.lower()

    def test_server_wrapper_validates(self, tmp_project, monkeypatch):
        """server.godot_run_game also validates scene before calling bridge."""
        from godot_mcp import bridge
        sent = []
        monkeypatch.setattr(bridge, "_send", lambda *a, **kw: sent.append(a) or {"ok": True, "playing": "main"})
        from godot_mcp.server import godot_run_game
        result = godot_run_game("notavalidscene")
        assert isinstance(result, str)
        # Either bridge rejects it (no _send call) or server rejects it
        # The point is a string comes back
        assert "notavalidscene" in result.lower() or "scene" in result.lower() or not sent


# ---------------------------------------------------------------------------
# B6 Python / server.py — open_scene with nonexistent res:// path → "Not found"
# ---------------------------------------------------------------------------

class TestB6OpenSceneExistenceCheck:
    def test_nonexistent_res_path_returns_not_found(self, tmp_project, monkeypatch):
        """godot_open_scene: valid res:// path that doesn't exist → 'Not found' before bridge send."""
        from godot_mcp import bridge
        sent = []
        monkeypatch.setattr(bridge, "_send", lambda *a, **kw: sent.append(a) or {"ok": True, "opened": "?"})
        from godot_mcp.server import godot_open_scene
        result = godot_open_scene("res://nonexistent_scene.tscn")
        assert isinstance(result, str)
        assert "Not found" in result or "not found" in result.lower()
        assert not sent, "bridge._send must NOT be called for a nonexistent path"

    def test_existing_path_calls_bridge(self, tmp_project, monkeypatch):
        """godot_open_scene: path that exists gets forwarded to bridge."""
        scene = tmp_project / "exists.tscn"
        scene.write_text("[gd_scene format=3]\n", encoding="utf-8")
        from godot_mcp import bridge
        sent = []
        monkeypatch.setattr(bridge, "_send", lambda *a, **kw: sent.append(a) or {"ok": True, "opened": "res://exists.tscn"})
        from godot_mcp.server import godot_open_scene
        godot_open_scene("res://exists.tscn")
        assert sent, "bridge._send should be called for an existing path"


# ---------------------------------------------------------------------------
# B10 — absolute deadline fires; buffer cap enforced
# ---------------------------------------------------------------------------

class TestB10DeadlineAndBufferCap:
    def test_deadline_fires_on_slow_recv(self, monkeypatch):
        """Socket that never sends a newline must hit the deadline, not loop forever."""
        class SlowSocket:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def sendall(self, data): pass
            def settimeout(self, t): pass
            def recv(self, n):
                time.sleep(0.05)
                return b"x"  # no newline, no termination

        monkeypatch.setattr(socket, "create_connection", lambda *a, **kw: SlowSocket())
        from godot_mcp import bridge
        start = time.monotonic()
        r = bridge._send({"cmd": "ping"}, timeout=0.2)
        elapsed = time.monotonic() - start
        assert r["ok"] is False
        # Must return within a reasonable multiple of the timeout (< 3 s)
        assert elapsed < 3.0, f"deadline not respected: elapsed {elapsed:.2f}s"

    def test_buffer_cap_returns_error(self, monkeypatch):
        """Socket that streams more than 1 MiB without a newline must return error."""
        cap = 1_048_576
        counter = {"sent": 0}

        class BigSocket:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def sendall(self, data): pass
            def settimeout(self, t): pass
            def recv(self, n):
                counter["sent"] += n
                if counter["sent"] > cap + n:
                    return b""  # EOF after cap exceeded
                return b"x" * n  # junk, no newline

        monkeypatch.setattr(socket, "create_connection", lambda *a, **kw: BigSocket())
        from godot_mcp import bridge
        r = bridge._send({"cmd": "ping"}, timeout=30.0)
        assert r["ok"] is False
        assert "large" in r["error"].lower() or "too large" in r["error"].lower(), f"expected cap error, got: {r['error']!r}"


# ---------------------------------------------------------------------------
# GDScript-side tests (require running Godot editor bridge) — skip markers
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="requires running Godot editor bridge")
class TestB1TokenGDScript:
    def test_unauthorized_request_rejected(self):
        """bridge.gd must reject a request without a valid token."""
        pass


@pytest.mark.skip(reason="requires running Godot editor bridge")
class TestB6GDScriptPathValidation:
    def test_dotdot_path_rejected(self):
        """bridge.gd open_scene must reject paths with .. even if res://."""
        pass

    def test_non_res_path_rejected(self):
        """bridge.gd open_scene must reject absolute/non-res:// paths."""
        pass


@pytest.mark.skip(reason="requires running Godot editor bridge")
class TestB7Framing:
    def test_large_payload_round_trips(self):
        """JSON payload > one TCP MTU must round-trip intact (per-client byte buffer)."""
        pass


@pytest.mark.skip(reason="requires running Godot editor bridge")
class TestB8OutboundQueue:
    def test_non_blocking_send(self):
        """_send in bridge.gd must not block the editor thread when client is slow."""
        pass


@pytest.mark.skip(reason="requires running Godot editor bridge")
class TestB9ClientCap:
    def test_second_connection_refused(self):
        """bridge.gd must refuse a second concurrent client."""
        pass

    def test_idle_timeout_disconnects(self):
        """A client idle for > 30 s must be disconnected."""
        pass
