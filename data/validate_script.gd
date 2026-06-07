extends SceneTree
# Headless parse-validator. Booting a SceneTree registers the project's autoloads as
# global identifiers (which `godot --check-only` never does), so the target then
# compiles with autoload references resolved. Force a fresh compile of the target.
#
# Verdict is decided by the CALLER from the engine log, not by this exit code:
#   - clean target      -> "VALIDATE_OK"   + no Parse/Compile error lines
#   - compile failure   -> "VALIDATE_OK"   + Parse/Compile error lines (load() returns
#                          non-null even on a compile error, so the log is the signal)
#   - missing / invalid -> "VALIDATE_NULL" (load() could not produce a resource at all)
func _initialize() -> void:
	var args: PackedStringArray = OS.get_cmdline_user_args()
	if args.is_empty():
		print("VALIDATE_NOARG")
		quit(2)
		return
	var res: Resource = ResourceLoader.load(args[0], "Script", ResourceLoader.CACHE_MODE_IGNORE)
	print("VALIDATE_NULL" if res == null else "VALIDATE_OK")
	quit(0)
