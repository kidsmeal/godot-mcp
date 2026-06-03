"""Phase 3 smoke test. Lint runs offline; write/patch run against a TEMP project
(capsulecastle is never touched)."""
import os
import pathlib
import sys
import tempfile

# Point the server at a throwaway project BEFORE importing config.
_tmp = tempfile.mkdtemp(prefix="godot_mcp_proj_")
pathlib.Path(_tmp, "project.godot").write_text(
    'config_version=5\n\n[application]\nconfig/name="lint_test"\n', encoding="utf-8"
)
os.environ["GODOT_PROJECT"] = _tmp

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from godot_mcp import edit, lint  # noqa: E402

CC = pathlib.Path(r"C:\Users\atk67\Documents\capsulecastle")


def show(title, body):
    print(f"\n===== {title} =====")
    print(body)


GOOD = (
    "class_name FooBar\n"
    "extends Node\n\n"
    "signal health_changed(new_value: int)\n\n"
    "const MAX_HP: int = 100\n\n"
    "var current_hp: int = 100\n\n"
    "func take_damage(amount: int) -> void:\n"
    "    current_hp -= amount\n"
)
BAD = (
    "class_name foo_bar\n"
    "extends Node\n\n"
    "signal on_died\n\n"
    "var x = 5\n\n"
    'var icon = "res://.godot/imported/foo.png-abc.ctex"\n\n'
    "func Update(a, b):\n"
    "    return a\n"
)

show("lint GOOD (expect clean)", lint.format_findings(lint.lint_source(GOOD, "res://foo_bar.gd")))
show("lint BAD (expect many)", lint.format_findings(lint.lint_source(BAD, "res://foo_bar.gd")))

# False-positive check against real, known-clean strict-typed files.
for rel in ["systems/combat/damage_types.gd", "heroes/hero_base.gd"]:
    p = CC / rel
    if p.exists():
        f = lint.lint_source(p.read_text(encoding="utf-8", errors="replace"), "res://" + rel)
        errs = [x for x in f if x["severity"] == "error"]
        show(f"lint REAL {rel}", f"{len(f)} findings, {len(errs)} errors\n" + lint.format_findings(errs[:12]))

show("write_script GOOD (temp project)", edit.write_script("res://foo_bar.gd", GOOD))
show("write_script BROKEN (expect rollback)", edit.write_script("res://broken.gd", "func oops( ->:\n"))
show("patch_script (temp project)", edit.patch_script("res://foo_bar.gd", "current_hp -= amount", "current_hp -= amount\n    current_hp = max(current_hp, 0)"))
