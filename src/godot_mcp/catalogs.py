"""Project catalogs parsed straight from source.

The game's content contracts live in GDScript (data-is-code): effect_types in
UpgradeEffectRegistry, sticker bases in the sticker catalog, damage types, and
autoloads. Surfacing the *real* registered values stops the agent inventing
effect_type/sticker keys that don't exist.
"""
from __future__ import annotations

import re

from godot_mcp import config


def _read(rel: str) -> str:
    return config.read_text(config.PROJECT_ROOT / rel) or ""


def effect_types() -> tuple[list[str], str]:
    text = _read("systems/upgrades/upgrade_effect_registry.gd")
    ids = sorted(set(re.findall(r'register_effect_processor\(\s*&"([^"]+)"', text)))
    dyn = sorted(set(re.findall(r'StringName\("%s_([a-z_]+)"', text)))
    note = ""
    if dyn:
        note = "\n\n(+ dynamic per-damage-type aliases: <damage_type>_" + ", <damage_type>_".join(dyn) + ")"
    return ids, note


def sticker_bases() -> list[tuple[str, str]]:
    text = _read("stickers/sticker_catalog.gd")
    out: list[tuple[str, str]] = []
    for key, body in re.findall(r'&"([A-Za-z0-9_]+)":\s*\{([^}]*)\}', text):
        dn = re.search(r'"display_name":\s*"([^"]+)"', body)
        out.append((key, dn.group(1) if dn else ""))
    return out


def damage_types() -> list[tuple[str, str]]:
    text = _read("systems/combat/damage_types.gd")
    return re.findall(r'const\s+([A-Z_]+)\s*:\s*StringName\s*=\s*&"([^"]+)"', text)


def autoloads() -> list[tuple[str, str]]:
    text = _read("project.godot")
    m = re.search(r"\[autoload\](.*?)(?:\n\[|\Z)", text, re.S)
    if not m:
        return []
    return re.findall(r'^([A-Za-z0-9_]+)="(\*?res://[^"]+)"', m.group(1), re.M)


def catalog(kind: str = "all") -> str:
    kind = kind.lower().strip()
    if kind in ("effect_types", "effects", "effect"):
        ids, note = effect_types()
        return f"Registered effect_types ({len(ids)}):\n" + "\n".join(ids) + note
    if kind in ("sticker_bases", "stickers", "sticker"):
        s = sticker_bases()
        return f"Sticker bases ({len(s)}):\n" + "\n".join(f"{k}  - {n}" for k, n in s)
    if kind in ("damage_types", "damage"):
        d = damage_types()
        return "Damage types:\n" + "\n".join(f"{k} = {v}" for k, v in d)
    if kind in ("autoloads", "singletons"):
        a = autoloads()
        return "Autoloads:\n" + "\n".join(f"{k} -> {v}" for k, v in a)
    if kind == "all":
        return "\n\n".join(catalog(k) for k in ("effect_types", "sticker_bases", "damage_types", "autoloads"))
    return f'Unknown catalog "{kind}". Options: effect_types, sticker_bases, damage_types, autoloads, all.'
