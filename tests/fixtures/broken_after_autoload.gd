# DELIBERATE negative fixture — DO NOT stage into a game project.
# This file is syntactically valid but references an undeclared identifier.
# Under --check-only (no SceneTree) the parse succeeds because autoloads are
# not registered; under godot_validate (SceneTree boot) this should FAIL with
# an "not declared in the current scope" error.
extends Node

func _ready() -> void:
	# UndeclaredAutoload does not exist in any real project — deliberate.
	UndeclaredAutoload.do_something()
