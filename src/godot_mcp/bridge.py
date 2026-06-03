"""Feature E: MCP-side client for the live editor bridge.

Talks newline-delimited JSON over TCP to the 'Godot Grounding Bridge' EditorPlugin
running inside an open Godot editor. Graceful when the editor/addon isn't running.
"""
from __future__ import annotations

import json
import os
import socket


def _port() -> int:
    try:
        return int(os.environ.get("GODOT_BRIDGE_PORT", "9123"))
    except ValueError:
        return 9123


def _send(cmd: dict, timeout: float = 6.0) -> dict:
    try:
        with socket.create_connection(("127.0.0.1", _port()), timeout=timeout) as s:
            s.sendall((json.dumps(cmd) + "\n").encode("utf-8"))
            s.settimeout(timeout)
            buf = b""
            while b"\n" not in buf:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
            return json.loads(buf.split(b"\n", 1)[0].decode("utf-8"))
    except (ConnectionRefusedError, TimeoutError, OSError):
        return {"ok": False, "error": (
            f"editor bridge not reachable on 127.0.0.1:{_port()} — open the project in the "
            "Godot editor with the 'Godot Grounding Bridge' addon enabled "
            "(Project > Project Settings > Plugins)."
        )}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"bridge error: {e}"}


def ping() -> str:
    r = _send({"cmd": "ping"})
    return f"Editor bridge OK — Godot {r.get('version', '?')}" if r.get("ok") else r["error"]


def run_game(scene: str = "main") -> str:
    r = _send({"cmd": "run", "scene": scene})
    return f"Playing {r.get('playing', '?')} scene." if r.get("ok") else r["error"]


def stop_game() -> str:
    r = _send({"cmd": "stop"})
    return "Stopped the running scene." if r.get("ok") else r["error"]


def is_playing() -> str:
    r = _send({"cmd": "is_playing"})
    return ("playing" if r.get("playing") else "not playing") if r.get("ok") else r["error"]


def scene_tree() -> str:
    r = _send({"cmd": "scene_tree"})
    return r.get("tree", "") if r.get("ok") else r["error"]


def open_scene(path: str) -> str:
    r = _send({"cmd": "open_scene", "path": path})
    return f"Opened {r.get('opened', '?')} in the editor." if r.get("ok") else r["error"]
