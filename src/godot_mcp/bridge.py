"""Feature E: MCP-side client for the live editor bridge.

Talks newline-delimited JSON over TCP to the 'Godot Grounding Bridge' EditorPlugin
running inside an open Godot editor. Graceful when the editor/addon isn't running.
"""
from __future__ import annotations

import json
import os
import socket
import tempfile
import time


def _port() -> int:
    try:
        return int(os.environ.get("GODOT_BRIDGE_PORT", "9123"))
    except ValueError:
        return 9123


def _token_path() -> str:
    return os.path.join(tempfile.gettempdir(), "godot_mcp_bridge.token")


def _read_token() -> str:
    try:
        with open(_token_path(), encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def _send(cmd: dict, timeout: float = 6.0) -> dict:
    cmd = {**cmd, "token": _read_token()}
    deadline = time.monotonic() + timeout
    try:
        with socket.create_connection(("127.0.0.1", _port()), timeout=timeout) as s:
            s.sendall((json.dumps(cmd) + "\n").encode("utf-8"))
            buf = b""
            while b"\n" not in buf:
                remain = deadline - time.monotonic()
                if remain <= 0:
                    return {"ok": False, "error": "editor bridge timed out — Godot may be busy or the addon is frozen"}
                s.settimeout(min(remain, 1.0))
                try:
                    chunk = s.recv(4096)
                except TimeoutError:
                    return {"ok": False, "error": "editor bridge timed out — Godot may be busy or the addon is frozen"}
                if not chunk:
                    break
                buf += chunk
                if len(buf) > 1_048_576:
                    return {"ok": False, "error": "bridge response too large (> 1 MiB)"}
            try:
                return json.loads(buf.split(b"\n", 1)[0].decode("utf-8"))
            except json.JSONDecodeError:
                return {"ok": False, "error": "bridge returned invalid JSON (empty or malformed response)"}
    except ConnectionRefusedError:
        return {"ok": False, "error": (
            f"editor bridge not reachable on 127.0.0.1:{_port()} — open the project in the "
            "Godot editor with the 'Godot Grounding Bridge' addon enabled "
            "(Project > Project Settings > Plugins)."
        )}
    except TimeoutError:
        return {"ok": False, "error": "editor bridge timed out — Godot may be busy or the addon is frozen"}
    except (ConnectionResetError, OSError):
        return {"ok": False, "error": "editor bridge disconnected unexpectedly"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"bridge error: {e}"}


def ping() -> str:
    r = _send({"cmd": "ping"})
    if r.get("ok"):
        bv = r.get("bridge_version", "?")
        return f"Editor bridge OK — Godot {r.get('version', '?')} (protocol {bv})"
    return r.get("error", "bridge returned a malformed response")


def run_game(scene: str = "main") -> str:
    if scene not in {"main", "current"}:
        return f"unknown scene value: {scene!r} (use 'main' or 'current')"
    r = _send({"cmd": "run", "scene": scene})
    return f"Playing {r.get('playing', '?')} scene." if r.get("ok") else r.get("error", "bridge returned a malformed response")


def stop_game() -> str:
    r = _send({"cmd": "stop"})
    return "Stopped the running scene." if r.get("ok") else r.get("error", "bridge returned a malformed response")


def is_playing() -> str:
    r = _send({"cmd": "is_playing"})
    return ("playing" if r.get("playing") else "not playing") if r.get("ok") else r.get("error", "bridge returned a malformed response")


def scene_tree() -> str:
    r = _send({"cmd": "scene_tree"})
    return r.get("tree", "") if r.get("ok") else r.get("error", "bridge returned a malformed response")


def open_scene(path: str) -> str:
    r = _send({"cmd": "open_scene", "path": path})
    return f"Opened {r.get('opened', '?')} in the editor." if r.get("ok") else r.get("error", "bridge returned a malformed response")
