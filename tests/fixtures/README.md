# tests/fixtures — deliberate negative fixtures

These GDScript files are **intentionally broken**. They exist to verify that
the linter and `godot_validate` harness correctly detect errors.

| File | What is broken |
|---|---|
| `broken_syntax.gd` | Syntax error — uncompilable (`func broken_syntax(` missing `)`) |
| `broken_after_autoload.gd` | References an undeclared identifier (`UndeclaredAutoload`) |

**Do NOT copy or stage these files into a game project.** `broken_syntax.gd`
will break a full-project headless parse if included in the project source tree.
`broken_after_autoload.gd` will cause a `not declared` error when the SceneTree
boots and real autoloads attempt to resolve.

These files live in the plugin repo (`godot-mcp/tests/fixtures/`) where no full
Godot project parse runs against them.
