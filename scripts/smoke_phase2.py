"""Smoke test for Phase 2 validation wrappers (actually launches Godot headless)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from godot_mcp import config, runner  # noqa: E402


def show(title, body):
    print(f"\n===== {title} =====")
    print(body)


show("resolve_godot()", config.resolve_godot())
show("godot_run_tests(filter='wave_clock')", runner.run_tests("wave_clock", timeout=120))
show("godot_check(damage_types.gd)", runner.check_script("res://systems/combat/damage_types.gd"))
