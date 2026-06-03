---
name: godot
description: Use when editing this Godot 4.6 project (GDScript, scenes, systems, heroes, enemies, upgrades, UI) — phrases like "fix/add/change ... in Godot", "edit the <system>", or /godot. Activates Godot mode — ground every engine API and project value via the godot-grounding MCP, edit through the convention-linted writer, and confirm with the headless tests. Delegates multi-file work to the godot-editor subagent.
version: 1.0.0
---

# Godot Mode

Disciplined editing for Capsule Castle (Godot 4.6.2, GDScript, data-is-code), backed by the `godot-grounding` MCP (16 tools). The loop is **GROUND → EDIT (linted) → CONFIRM**. Work Mode response rules stay in effect (terse).

If the `godot-grounding` tools are unavailable, stop and tell the user to reconnect the MCP server (`/mcp`) before continuing — do not fall back to ungrounded edits.

## When to delegate
For a multi-file change (new hero/enemy/system, cross-cutting refactor), hand off to the **godot-editor** subagent with a clear task and file list. For a single-file or small change, run the loop inline.

## Stage 0 — Ground (no guessing)
1. `capsule_index` to locate the system; `capsule_find_files` to enumerate files (never glob — it silently misses files here).
2. `capsule_convention('<topic>')` for the rules that apply (signal naming, enemy creation, upgrade pool, …).
3. `capsule_catalog('<kind>')` to confirm valid `effect_type` / sticker / damage-type / autoload values before you use any.
4. `godot_member` / `godot_class` / `godot_search` for the exact 4.6 signature before any engine call.
5. Read each target file end-to-end before editing.

## Stage 1 — Edit (linted)
- `.gd`: `godot_write_script` (new / full rewrite) or `godot_patch_script` (targeted, exact-match). **Never** raw `Write`/`Edit` on a `.gd` file.
- Optionally `godot_lint_source` the generated code first; fix every lint `error`.
- Writes auto parse-check and roll back on failure — a rollback means fix and retry, never force.

## Stage 2 — Confirm
- `godot_check` each touched script.
- `godot_run_tests` filtered to the area (`filter='…'`); full suite for cross-cutting changes. Enemies: `godot_verify_enemies`.
- Report **changes → grounding → test result**. Not done until green.

## Hard rules
- Never raw-write `.gd`; never reference `.godot/imported/`; reference assets by canonical `res://` paths only.
- Strict typing everywhere; past-tense `snake_case` signals (no `on_`); PascalCase `class_name`; ALL_CAPS consts; new folders lowercase.
- `ext_resource` ids are serializer-local — never depend on numeric ids across files.
- Folder renames only via the Godot editor. Do not commit/push — the human gates that.

## Tool reference
| Need | Tool |
|---|---|
| Exact 4.6 class/method/signal signature | `godot_class` / `godot_member` / `godot_search` |
| Valid effect_type / sticker / damage / autoload | `capsule_catalog` |
| A project convention / rule | `capsule_convention` |
| Where a system lives | `capsule_index` |
| Reliable file listing | `capsule_find_files` |
| Lint a file / a snippet | `godot_lint` / `godot_lint_source` |
| Write / patch a `.gd` (linted, rollback) | `godot_write_script` / `godot_patch_script` |
| Parse-check one script | `godot_check` |
| Run the suite (filtered) | `godot_run_tests` |
| Validate enemies / run a SceneTree script | `godot_verify_enemies` / `godot_run_script` |
