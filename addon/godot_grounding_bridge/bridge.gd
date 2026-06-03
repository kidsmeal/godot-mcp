@tool
extends EditorPlugin

## Live editor bridge for the godot-grounding MCP.
## Listens on 127.0.0.1:<PORT> and answers newline-delimited JSON commands so an agent
## can drive the editor: ping, run/stop the game, open scenes, read the edited scene tree.
## Read-only-ish: it only calls EditorInterface play/stop/open + walks the scene tree.

const PORT := 9123

var _server := TCPServer.new()
var _clients: Array[StreamPeerTCP] = []


func _enter_tree() -> void:
	var err := _server.listen(PORT, "127.0.0.1")
	if err != OK:
		push_warning("godot-grounding bridge: could not listen on %d (%s)" % [PORT, error_string(err)])
	else:
		print("godot-grounding bridge: listening on 127.0.0.1:%d" % PORT)
	set_process(true)


func _exit_tree() -> void:
	set_process(false)
	_server.stop()
	for c in _clients:
		c.disconnect_from_host()
	_clients.clear()


func _process(_delta: float) -> void:
	if _server.is_listening() and _server.is_connection_available():
		_clients.append(_server.take_connection())
	for c: StreamPeerTCP in _clients.duplicate():
		c.poll()
		if c.get_status() != StreamPeerTCP.STATUS_CONNECTED:
			_clients.erase(c)
			continue
		var avail := c.get_available_bytes()
		if avail > 0:
			for req in c.get_utf8_string(avail).split("\n", false):
				_send(c, _dispatch(JSON.parse_string(req)))


func _send(c: StreamPeerTCP, obj: Dictionary) -> void:
	c.put_data((JSON.stringify(obj) + "\n").to_utf8_buffer())


func _dispatch(req: Variant) -> Dictionary:
	if typeof(req) != TYPE_DICTIONARY:
		return {"ok": false, "error": "invalid json request"}
	var cmd := String(req.get("cmd", ""))
	match cmd:
		"ping":
			return {"ok": true, "version": String(Engine.get_version_info().get("string", ""))}
		"is_playing":
			return {"ok": true, "playing": EditorInterface.is_playing_scene()}
		"run":
			if String(req.get("scene", "main")) == "current":
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
			EditorInterface.open_scene_from_path(path)
			return {"ok": true, "opened": path}
		"save_scene":
			return {"ok": EditorInterface.save_scene() == OK}
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
