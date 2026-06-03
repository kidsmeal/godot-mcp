"""Parity test: the profile-driven (generic) build must reproduce the Capsule results."""
import collections
import os
import pathlib
import sys

sys.path.insert(0, r"C:\Users\atk67\Documents\godot-mcp\src")
from godot_mcp import catalogs, config, lint, project_ground

print("PROFILE:", config.PROFILE.name, "| godot_bin:", config.GODOT_BIN)
print("suite:", config.PROFILE.suite_scene, "| integration:", config.PROFILE.integration_scene)
print("docs:", list(config.PROFILE.docs))
print("catalogs:", [c["name"] for c in config.PROFILE.catalogs])

print("\neffect_types:", catalogs.catalog("effect_types").splitlines()[0])
print("damage_types:", catalogs.catalog("damage_types").splitlines()[0])
print("sticker_bases:", catalogs.catalog("sticker_bases").splitlines()[0])
print("autoloads:", catalogs.catalog("autoloads").splitlines()[0])
print("index head:", project_ground.index().splitlines()[0])
print("convention('signal') head:", project_ground.convention("signal").splitlines()[0])

refs = catalogs.build_catalog_refs()
print("\ncatalog_refs:", [(r["use_pattern"][:22], "valid=" + str(len(r["valid_set"]))) for r in refs])
CAT_BAD = 'extends Node\nfunc f() -> Array:\n\treturn [{"effect_type": &"damage_flat_addd"}]\n'
print("typo test:", lint.format_findings(lint.lint_source(CAT_BAD, "res://h.gd", catalog_refs=refs)))

ML = "extends Node\n\nfunc cast(\n\t\ttarget,\n\t\tpower: float) -> void:\n\tvar n = target\n\tprint(n, power)\n"
print("multi-line:", lint.format_findings(lint.lint_source(ML)).replace(chr(10), " | "))
SUP = "extends Node\n\nvar x = 5  # lint: ignore\nvar z = 7\n"
print("suppression (only z flagged):", lint.format_findings(lint.lint_source(SUP)).replace(chr(10), " | "))

CC = config.PROJECT_ROOT
skip = {".godot", ".git", ".import"}
files = []
for dp, dn, fn in os.walk(CC):
    dn[:] = [d for d in dn if d not in skip]
    files += [pathlib.Path(dp, f) for f in fn if f.endswith(".gd")]
err_files = total_err = fallback = 0
by_rule = collections.Counter()
for p in files:
    rel = "res://" + str(p.relative_to(CC)).replace("\\", "/")
    f = lint.lint_source(p.read_text(encoding="utf-8", errors="replace"), rel, catalog_refs=refs)
    if any(x["rule"] == "parser" for x in f):
        fallback += 1
    errs = [x for x in f if x["severity"] == "error"]
    if errs:
        err_files += 1
        total_err += len(errs)
    for x in f:
        by_rule[x["rule"]] += 1
print(f"\nSWEEP {len(files)} files: err_files={err_files} total_err={total_err} fallback={fallback}")
print("by rule:", dict(by_rule))
print("EXPECT: err_files=13 total_err=73 fallback=1 unknown-catalog-key=0")
