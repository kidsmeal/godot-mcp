@tool
extends EditorPlugin

## Live editor bridge for the godot-grounding MCP.
## Listens on 127.0.0.1:<PORT> and answers newline-delimited JSON commands so an agent
## can drive the editor: ping, run/stop the game, open scenes, read the edited scene tree.
## Read-only-ish: it only calls EditorInterface play/stop/open + walks the scene tree.

const DEFAULT_PORT := 9123
const MAX_CLIENTS := 1
const _BUF_CAP := 1_048_576  # 1 MiB per-client buffer cap

var _server := TCPServer.new()
var _clients: Array[StreamPeerTCP] = []
var _port := DEFAULT_PORT

# Per-client receive buffers (peer instance id → PackedByteArray)
var _bufs: Dictionary = {}
# Per-client outbound byte queues (peer instance id → PackedByteArray)
var _out_bufs: Dictionary = {}
# Per-client last-activity timestamps in ms (peer instance id → int)
var _idle_times: Dictionary = {}

# Auth token (32 hex chars) written to OS temp dir; read by bridge.py on each call
var _token: String = ""
var _token_file: String = ""


## Honor GODOT_BRIDGE_PORT so the addon and the MCP client agree on the port
## (the Python side reads the same env var). Both processes must see it set.
func _resolve_port() -> int:
	var env := OS.get_environment("GODOT_BRIDGE_PORT")
	if not env.is_empty() and env.is_valid_int():
		return env.to_int()
	return DEFAULT_PORT


func _generate_token() -> String:
	var parts: Array[String] = []
	for _i in range(8):
		parts.append("%08x" % (randi()))
	return "".join(parts)


func _enter_tree() -> void:
	_port = _resolve_port()
	_token = _generate_token()
	_token_file = OS.get_temp_dir().path_join("godot_mcp_bridge.token")
	var fa := FileAccess.open(_token_file, FileAccess.WRITE)
	if fa != null:
		fa.store_string(_token)
		fa.close()
	else:
		push_warning("godot-grounding bridge: could not write token file %s" % _token_file)
	var err := _server.listen(_port, "127.0.0.1")
	if err != OK:
		push_warning("godot-grounding bridge: could not listen on %d (%s)" % [_port, error_string(err)])
	else:
		print("godot-grounding bridge: listening on 127.0.0.1:%d" % _port)
	set_process(true)


func _exit_tree() -> void:
	set_process(false)
	_server.stop()
	for c in _clients:
		c.disconnect_from_host()
	_clients.clear()
	_bufs.clear()
	_out_bufs.clear()
	_idle_times.clear()
	if not _token_file.is_empty():
		DirAccess.remove_absolute(_token_file)


func _process(_delta: float) -> void:
	if _server.is_listening() and _server.is_connection_available():
		var incoming: StreamPeerTCP = _server.take_connection()
		if _clients.size() >= MAX_CLIENTS:
			incoming.disconnect_from_host()
		else:
			_clients.append(incoming)
			var iid := incoming.get_instance_id()
			_bufs[iid] = PackedByteArray()
			_out_bufs[iid] = PackedByteArray()
			_idle_times[iid] = Time.get_ticks_msec()

	var now_ms := Time.get_ticks_msec()
	for c: StreamPeerTCP in _clients.duplicate():
		c.poll()
		var iid := c.get_instance_id()
		if c.get_status() != StreamPeerTCP.STATUS_CONNECTED:
			_clients.erase(c)
			_bufs.erase(iid)
			_out_bufs.erase(iid)
			_idle_times.erase(iid)
			continue

		# Idle timeout: 30 seconds of no data
		if now_ms - _idle_times.get(iid, 0) > 30_000:
			c.disconnect_from_host()
			_clients.erase(c)
			_bufs.erase(iid)
			_out_bufs.erase(iid)
			_idle_times.erase(iid)
			continue

		var avail := c.get_available_bytes()
		if avail > 0:
			_idle_times[iid] = now_ms
			var result := c.get_partial_data(avail)
			# result[0] is the error code; result[1] is the PackedByteArray
			if result[0] == OK:
				var incoming_bytes: PackedByteArray = result[1]
				if not _bufs.has(iid):
					_bufs[iid] = PackedByteArray()
				_bufs[iid].append_array(incoming_bytes)

				# Buffer cap: drop oversized client
				if _bufs[iid].size() > _BUF_CAP:
					c.disconnect_from_host()
					_clients.erase(c)
					_bufs.erase(iid)
					_out_bufs.erase(iid)
					_idle_times.erase(iid)
					continue

				# Dispatch each complete newline-terminated line
				while true:
					var nl_idx := _bufs[iid].find(10)  # byte 10 = '\n'
					if nl_idx < 0:
						break
					var line_bytes := _bufs[iid].slice(0, nl_idx)
					_bufs[iid] = _bufs[iid].slice(nl_idx + 1)
					var line := line_bytes.get_string_from_utf8()
					_enqueue_send(c, _dispatch(JSON.parse_string(line)))

		# Flush outbound queue with put_partial_data to avoid blocking
		if _out_bufs.has(iid) and _out_bufs[iid].size() > 0:
			var flush_result := c.put_partial_data(_out_bufs[iid])
			# flush_result[0] = error, flush_result[1] = bytes actually written
			if flush_result[0] == OK:
				var written: int = flush_result[1]
				if written > 0:
					_out_bufs[iid] = _out_bufs[iid].slice(written)


func _enqueue_send(c: StreamPeerTCP, obj: Dictionary) -> void:
	var iid := c.get_instance_id()
	if not _out_bufs.has(iid):
		_out_bufs[iid] = PackedByteArray()
	_out_bufs[iid].append_array((JSON.stringify(obj) + "\n").to_utf8_buffer())


func _dispatch(req: Variant) -> Dictionary:
	if typeof(req) != TYPE_DICTIONARY:
		return {"ok": false, "error": "invalid json request"}
	# Auth token check (allow through if token is empty — startup race guard)
	if not _token.is_empty() and String(req.get("token", "")) != _token:
		return {"ok": false, "error": "unauthorized"}
	var cmd := String(req.get("cmd", ""))
	match cmd:
		"ping":
			return {"ok": true, "version": String(Engine.get_version_info().get("string", "")), "bridge_version": "1.0"}
		"is_playing":
			return {"ok": true, "playing": EditorInterface.is_playing_scene()}
		"run":
			var scene_val := String(req.get("scene", "main"))
			if scene_val not in ["main", "current"]:
				return {"ok": false, "error": "unknown scene value: " + scene_val + " (use 'main' or 'current')"}
			if scene_val == "current":
				EditorInterface.play_current_scene()
				return {"ok": true, "playing": "current"}
			EditorInterface.play_main_scene()
			return {"ok": true, "playing": "main"}
		"stop":
			EditorInterface.stop_playing_scene()
			return {"ok": true}
		"open_scene":
			var path := String(req.get("path", ""))
			if path.is_empty():
				return {"ok": false, "error": "no path"}
			if not path.begins_with("res://") or ".." in path:
				return {"ok": false, "error": "path must be a res:// path and must not contain .."}
			EditorInterface.open_scene_from_path(path)
			return {"ok": true, "opened": path}
		"scene_tree":
			var root := EditorInterface.get_edited_scene_root()
			if root == null:
				return {"ok": true, "tree": "(no scene open in the editor)"}
			return {"ok": true, "tree": _tree(root, 0)}
		_:
			return {"ok": false, "error": "unknown cmd: " + cmd}


func _tree(node: Node, depth: int) -> String:
	var line := "  ".repeat(depth) + node.name + " [" + node.get_class() + "]"
	if node.get_script() != null:
		line += " (script)"
	for child in node.get_children():
		line += "\n" + _tree(child, depth + 1)
	return line
