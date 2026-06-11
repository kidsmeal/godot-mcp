# NOW (read me first)

<!-- claudhd: opt-in marker (do not remove) - ClauDHD's hooks only act on a NOW.md that has this line -->

One active thread at a time. This file is the cursor: what is live, the next physical action, and what is queued behind it. Read it first, update it as you go.

_Committed, so it follows your branch: `git checkout` swaps this cursor to that branch's thread._

Last touched: 2026-06-10

## Active thread (only one)

**Feature Batch F–H — gated Gantry pipeline (correctness-first hardening → features)**

Phases 1–4 shipped: containment, validator-harness leak fix, engine-grounding correctness, profile robustness, + ruff/mypy/CI. 99 tests green; `main` == `origin/main` (last: `bbf5df8`, Phase 4). Plan: `docs/design/feature-batch-fgh.plan.md`. Loop per phase: implementer → phase-reviewer → fix/re-review → commit + push (human-gated at each commit).

Next physical action:

- [x] Phase 5 shipped — `feace6d` committed + pushed. 142 tests green, ruff/mypy clean.
- [x] 2026-06-10 full code audit ran (5 parallel reviewers) — ~45 deduped findings bucketed in `docs/CODE_AUDIT_2026-06-10.md` (A = Phase 5 diff, B = Phase 6 additions, C = new hardening phase, D = parked portability/CI).
- [x] Audit bucket A fixes shipped — `b0bbabd`. 142 tests green, ruff/mypy clean.
- [x] Phase 6 plan amended with bucket B (B1–B10).
- [x] Phase 6 shipped — bridge hardening + auth + protocol fixes. 162 tests green, ruff/mypy clean.
- [x] Phase 6.5 plan written (6 phases, C15/C16 first). Phase 6.5-P1 (crash class) shipped — 185 tests green.
- [x] Phase 6.5-P2 shipped — validation correctness + env-vs-parse verdict (C5, C8–C14). 203 tests green.
- [x] Phase 6.5-P3 shipped — edit-path integrity (C1–C4, C6, C7-partial). 221 tests green. `f196fed`
- [x] Phase 6.5-P4 shipped — engine API indexing + search ranking (C17, C21, C22). 249 tests green. `aecb79e`
- [x] Phase 6.5-P5 shipped — docs fetch + cache correctness (C18, C19, C20). 269 tests green. (+ fixed flaky import-safety tests: `0778033`)
- [ ] **Phase 6.5-P6** — doctor drift + remaining grounding parsers (C17-doctor, C23–C31 where cheap). First action: gantry:build Phase 6.

Rule: when you finish a step, check it off and write the next single tiny step. Do not start another thread until this one ships or you consciously move it to the Queue.

## Queue (in order, not now)

What is eligible to become active next, in order. Items clear triage's readiness gate before they land here: each is either a ready task (carries a one-line "done" + first action) or a spike (the unknown to resolve before it can be built). Nothing queues as a bare one-liner.

1. **Phase 6 — Bridge hardening** (prereq for G/H). Done = per-client TCP buffers/framing + distinct `protocol`/`bridge_version` field in `ping` + a doctor check, **plus audit bucket B** (`docs/CODE_AUDIT_2026-06-10.md`): B1 auth token on the command channel, B2 remove the live `save_scene` branch, B3/B4 bridge.py error-reporting fixes, B5/B6 `run`/`open_scene` validation, B7-B10 framing/byte-level caps + outbound queue + client cap. First action: amend the Phase 6 plan section with bucket B, then implementer.
2. **Phase 6.5 — audit hardening batch** (bucket C; correctness-first, before features). Done = edit-path integrity (C1 rollback try/except, C2 CRLF preserve, C3/C4 UTF-8 strictness + string-aware auto_fix, **C5 env-failure vs parse-failure verdicts** — stance rule 7, retry elimination), validation false-FAIL fixes (C8/C9/C10), crash class (C15 profile shape validation, C16 `.mcp.json` clobber), grounding data (C17 utility/global-enum indexing + doctor binary-version check, C18 docs `.0` tag, C19 version-keyed doc cache, **C20 offline circuit breaker, C21 search ranking** — stance rule 7). Remaining mediums/lows in the doc ride along where cheap. First action: gantry:plan an addendum phase from bucket C.
3. **Phase 6.6 — tool-surface settle** (stance rules 4/5/6; do while zero external users). Done = (a) permanent naming scheme applied: `godot_*` engine grounding + validate/edit/test, `project_*` project grounding, `editor_*` live editor bridge — proposed rename map: `godot_editor_ping`→`editor_ping`, `godot_editor_scene_tree`→`editor_scene_tree`, `godot_run_game`→`editor_run_game`, `godot_stop_game`→`editor_stop_game`, `godot_open_scene`→`editor_open_scene`; README + agent templates + `ci_smoke` roster updated in the same diff; (b) MCP server `instructions` block carrying the shared semantics (res:// rules, "Refused" shape, `# lint: ignore` syntax, the ground→edit→confirm loop) + a docstring slim pass against it; (c) response caps on the known-fat tools (C22: `godot_class` char budget + drill-down tail; doc descriptions first-sentence by default, `full_docs=True` param). First action: human confirms the rename map, then implementer.
4. **Phase 7 — Feature G: runtime loop**. Done = `godot_run_game_headless` (+ empirical `--quit-after` exit-code check) + `godot_screenshot` (editor viewport) + `godot_validate_scene_load`. Carry: add a bare `ERROR:`/runtime marker to the verdict once probes execute code.
5. **Phase 8 — Feature H: scene authoring** (gated on Phases 1, 6, and `validate_scene_load`). Done = 5 bridge mutation cmds + undo + reload-check + a provable-rollback test. Carry into the design before build: **UID-sidecar rule** — any tool that creates/moves/renames a `.gd`/`.gdshader` must create/move the `.uid` sidecar with it (capsulecastle is fully UID-migrated, 735 sidecars; a missed sidecar silently re-IDs the file and rots `uid://` refs in scenes).
6. **Portability + CI batch** (audit bucket D; parked — moves up if external users become a goal). Done = `setup.ps1` works on stock PS 5.1 (D1), unix installs persist the located Godot (D2), no hardcoded capsulecastle default (D3), windows CI leg + pinned dev deps (D6), tests for the zero-coverage modules (D7). First action: spike D1/D2 on a clean VM or fresh user account.
7. **Feature batch I — grounding completion** (from the 2026-06-10 feature review; all offline, no new infra, same shape/size as Feature F). Done = (a) `res://` path-existence lint on the write path + standalone check (294 load/preload sites in capsulecastle; binary exact check, not near-miss), (b) `project_groups()` + near-miss typo-lint mirroring the input-action pattern (85 call sites, 9 group names, no registry exists anywhere — a typo'd group returns an empty array silently), (c) `project_script_api(path)` — methods/signals-with-arity/exports parsed per script, the project-side sibling of `godot_class` (grounds 690 signal use sites + the 13 autoload APIs), (d) `project_resource(path)` — read-only `.tres` summarizer, sibling of `project_scene` (374 files, 18 custom Resource classes). Carry into the design (stance rules 5/8): new surfaces label **static vs live** values the way `project_setting` does; `project_index` gains a one-line freshness read (map mtime vs files changed since). First action: gantry:draft the design doc.
8. **Batch J — verification upgrade** (spike). Unknown to resolve: connect to the editor's built-in GDScript LSP (port 6005; also runs windowless via `--headless --editor --lsp-port`) and verify it returns analyzer-grade diagnostics (type errors + warnings `--check-only` can't see, with autoloads resolved) against the 4.6.2 pin; it accepts multiple simultaneous clients. If the spike holds: LSP-backed `godot_check` with `--check-only` fallback + a project-wide error-sweep tool (didOpen-walk every `.gd`).
9. **Batch K — runtime game bridge** (gated on Phases 6 + 8: builds on bridge auth/framing). Done = injected-autoload bridge into the running game (zero addon footprint, injected at launch; reuses the editor-bridge protocol + auth): input simulation via `Input.parse_input_event`, live tree/state inspection, incremental error/log cursors, game screenshot via a windowed off-screen run (headless capture is a verified dead end — the dummy driver discards all rendering). The field's table-stakes loop we lack (9+ servers ship input sim). Carry into the design (stance rules 3/4): runtime family named `game_*` and registered behind a profile key resolved at startup only. First action: design doc.

## Quick fixes (clear in one pass)

Small, self-contained chores that need no plan and aren't worth their own thread. Capped at 5 — overflow means clear some or promote one out, so this stays a batch and never a second backlog. Add with `/claudhd:quick <text>`, clear them in one focused pass with `/claudhd:quick`. The active thread has right of way: clear these between threads, not mid-thread. A fix that turns out to need real thinking gets kicked back to IDEAS.md.

- Add per-call response-size logging to server.py (tool name + response chars, one log line per call) + a tiny report script — feeds stance rule 10 below.

## Idea flow (do not open a new chat)

New idea mid-task: `/claudhd:idea <text>` records it in IDEAS.md so you can keep working. `/claudhd:harvest` backfills ideas from past sessions you never recorded. `/claudhd:triage` clears the inbox. Finished work is recorded in SHIPPED.md via `/claudhd:shipped`.

## Loose ends

- **F-10 housekeeping:** `docs/CURRENTNESS_AUDIT.md` + `docs/RUNTIME_VERIFICATION_QUEUE.md` are untracked gantry placeholders (still `<DATE>`/`<path>`) — fill or remove before they rot. These are the only untracked files in the tree.
- **SHIPPED.md** is current through Phase 4; update it as later phases land (or via `/claudhd:shipped`).

## Standing stance — tool surface + token budget

Set 2026-06-10, while the server has **zero external users** — naming, ordering, and protocol changes are free until that changes. Every batch design and review should check against these.

1. **Never rollup, never thin docstrings.** The grounding/edit/test core stays first-class per-tool; docstrings ARE the agent-facing grounding (avg ~220 chars/tool today — already lean). The field's op-enum rollup pattern is rejected.
2. **Growth rule: variant = param, new noun = new tool.** `project_setting(resolve=True)` is the pattern. This is what actually prevents the 150-tool accretion the field hit; everything else is relief valves.
3. **Family flags at batch K.** Situational tool families (runtime bridge; optionally the editor bridge) register behind a profile key, resolved at **startup only**, never mid-session (prompt-cache stability).
4. **Settle permanent tool naming in Phase 6.6** (queue item 3 — Phase 6 was already mid-flight when this stance landed, so renames got their own small phase): family prefixes — `godot_*` engine grounding + validate/edit/test, `project_*` project grounding, `editor_*` live editor bridge, `game_*` batch-K runtime bridge. Once external users exist, renames become breaking changes.
5. **Responses are budgeted.** Compact by default, a param (`full=true` style) to go deep; anything that can exceed ~2k tokens returns a summary + file handle (the Phase-G screenshot decision, generalized); stream-shaped data (runtime logs/errors) uses incremental since-last-call cursors (batch K requirement). Results dwarf definitions: 30-50 calls/session × 1-2k tokens each vs ~2.6k of definitions once.
6. **Shared semantics live once in the MCP server `instructions` block** (res:// path rules, the "Refused" containment shape, `# lint: ignore` syntax, the ground → linted edit → test-to-confirm loop) — not repeated across 30 docstrings.
7. **Retry elimination is a token feature.** Misleading errors and bad rankings are budget bugs, not polish: every confusing verdict costs a full agent round-trip. Canonical examples from the audit: M1/C5 (env failure reported as "script does not parse" sends the agent into a fix-nothing loop), C21 (exact search match buried below truncation forces re-queries).
8. **Precomputed artifacts carry provenance and get a doctor line.** Stamp every generated artifact (API dump, docs cache, rendered agent templates, the codebase map `project_index` serves) with what it was generated from (engine version / date / commit). Doctor checks each for drift (C17 binary-vs-dump, C19 version-keyed docs cache already queued; add a `project_index` freshness read — map mtime vs files changed since). Borrowed from Gantry: artifact + cheap reconciliation pass + visible trust tier, instead of silent trust or constant regeneration.
9. **MCP resources: parked.** `godot://` read-only URIs are off-spec-cheap but client support is weak; watch, don't build.
10. **Instrument before optimizing further.** Per-call response-size telemetry (quick fix queued above); re-measure definition cost each batch (baseline 2026-06-10: 30 tools, ~6.5k docstring chars, ~2.6k tokens with schemas). Act on telemetry at >50 tools or >6k definition tokens — trim the actually-fat tools, not guesses.

## Leaving this file when you stop

Before you walk away, or whenever you switch context, make the "Next physical action" line true and tiny. That one line is what lets you stop mid-thought and lose nothing. The quick way: run `/claudhd:wrap` and it reconciles this file for you - checks off what's done, writes the next action, and closes out loose ends.
