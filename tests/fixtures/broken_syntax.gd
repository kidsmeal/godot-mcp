# DELIBERATE negative fixture — DO NOT stage into a game project.
# This file is intentionally uncompilable (syntax error).
# Used to verify that the linter / validator correctly detects parse errors.
extends Node

func broken_syntax( -> void:
	pass
