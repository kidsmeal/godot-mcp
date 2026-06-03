import collections
import os
import pathlib
import sys

sys.path.insert(0, r"C:\Users\atk67\Documents\godot-mcp\src")
from godot_mcp import catalogs, config, lint


def show(t, b):
    print(f"\n===== {t} =====\n{b}")


GOOD = (
    "class_name FooBar\nextends Node\n\n"
    "signal health_changed(new_value: int)\n\n"
    "const MAX_HP: int = 100\n\n"
    "var current_hp: int = 100\n\n"
    "func take_damage(amount: int) -> void:\n\tcurrent_hp -= amount\n"
)
MULTILINE = "extends Node\n\nfunc cast(\n\t\ttarget,\n\t\tpower: float) -> void:\n\tvar n = target\n\tprint(n, power)\n"
BAD = (
    "class_name foo_bar\nextends Node\n\nsignal on_died\n\n"
    "var x = 5\n\n"
    'var icon = "res://.godot/imported/foo.png-abc.ctex"\n\n'
    "func Update(a, b):\n\treturn a\n"
)
SUP = "extends Node\n\nvar x = 5  # lint: ignore\nvar y = 6  # lint: ignore=typed-var\nvar z = 7\n"

show("GOOD (expect clean)", lint.format_findings(lint.lint_source(GOOD, "res://foo.gd")))
show("MULTI-LINE (AST must catch untyped `target` regex missed)", lint.format_findings(lint.lint_source(MULTILINE, "res://foo.gd")))
show("BAD", lint.format_findings(lint.lint_source(BAD, "res://foo.gd")))
show("SUPPRESSION (only z flagged)", lint.format_findings(lint.lint_source(SUP, "res://foo.gd")))

valid = catalogs.valid_effect_types()
print(f"\nvalid effect_types known: {len(valid)}")
CAT_GOOD = 'extends Node\nfunc f() -> Array:\n\treturn [{"effect_type": &"damage_flat_add"}]\n'
CAT_BAD = 'extends Node\nfunc f() -> Array:\n\treturn [{"effect_type": &"damage_flat_addd"}]\n'
CAT_LOCAL = 'extends Node\nfunc _init() -> void:\n\tUpgradeEffectRegistry.register_effect_processor(&"hero_zz_special", _p)\nfunc f() -> Array:\n\treturn [{"effect_type": &"hero_zz_special"}]\n'
show("CATALOG ok key", lint.format_findings(lint.lint_source(CAT_GOOD, "res://h.gd", valid_effect_types=valid)))
show("CATALOG typo key (warn)", lint.format_findings(lint.lint_source(CAT_BAD, "res://h.gd", valid_effect_types=valid)))
show("CATALOG hero-local registered (no warn)", lint.format_findings(lint.lint_source(CAT_LOCAL, "res://h.gd", valid_effect_types=valid)))

# Full sweep
CC = config.PROJECT_ROOT
skip = {".godot", ".git", ".import"}
files = []
for dp, dn, fn in os.walk(CC):
    dn[:] = [d for d in dn if d not in skip]
    files += [pathlib.Path(dp, f) for f in fn if f.endswith(".gd")]

err_files = total_err = fallback = 0
by_rule = collections.Counter()
eff_ex = []
for p in files:
    rel = "res://" + str(p.relative_to(CC)).replace("\\", "/")
    f = lint.lint_source(p.read_text(encoding="utf-8", errors="replace"), rel, valid_effect_types=valid)
    if any(x["rule"] == "parser" for x in f):
        fallback += 1
    errs = [x for x in f if x["severity"] == "error"]
    if errs:
        err_files += 1
        total_err += len(errs)
    for x in f:
        by_rule[x["rule"]] += 1
        if x["rule"] == "unknown-effect-type" and len(eff_ex) < 20:
            eff_ex.append(f'{p.relative_to(CC)}:{x["line"]}  {x["message"]}')

print(f"\n=== SWEEP {len(files)} files ===")
print(f"files with errors: {err_files} | total errors: {total_err} | regex-fallback files: {fallback}")
print("by rule:", dict(by_rule))
print(f"\nunknown-effect-type warnings: {by_rule.get('unknown-effect-type', 0)} (false-positive risk check)")
for e in eff_ex:
    print("  ", e)
