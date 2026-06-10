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
- [ ] **Implement audit bucket A fixes** (A1–A6, uncommitted): A1 wrong `ui_*` roster, A2 lint.py valid_pattern re.error + group-less guard, A3 input-lint same-source exemption for `add_action`, A4 input-lint regex gaps, A5 validate setting name before probe, A6 fix resolve=True test to assert the right branch. Run `pytest`/`ruff`/`mypy` green, then commit + push.

Rule: when you finish a step, check it off and write the next single tiny step. Do not start another thread until this one ships or you consciously move it to the Queue.

## Queue (in order, not now)

What is eligible to become active next, in order. Items clear triage's readiness gate before they land here: each is either a ready task (carries a one-line "done" + first action) or a spike (the unknown to resolve before it can be built). Nothing queues as a bare one-liner.

1. **Phase 6 — Bridge hardening** (prereq for G/H). Done = per-client TCP buffers/framing + distinct `protocol`/`bridge_version` field in `ping` + a doctor check, **plus audit bucket B** (`docs/CODE_AUDIT_2026-06-10.md`): B1 auth token on the command channel, B2 remove the live `save_scene` branch, B3/B4 bridge.py error-reporting fixes, B5/B6 `run`/`open_scene` validation, B7-B10 framing/byte-level caps + outbound queue + client cap. First action: amend the Phase 6 plan section with bucket B, then implementer.
2. **Phase 6.5 — audit hardening batch** (bucket C; correctness-first, before features). Done = edit-path integrity (C1 rollback try/except, C2 CRLF preserve, C3/C4 UTF-8 strictness + string-aware auto_fix), validation false-FAIL fixes (C8/C9/C10), crash class (C15 profile shape validation, C16 `.mcp.json` clobber), grounding data (C17 utility/global-enum indexing + doctor binary-version check, C18 docs `.0` tag, C19 version-keyed doc cache). Mediums/lows in the doc ride along where cheap. First action: gantry:plan an addendum phase from bucket C.
3. **Phase 7 — Feature G: runtime loop**. Done = `godot_run_game_headless` (+ empirical `--quit-after` exit-code check) + `godot_screenshot` (editor viewport) + `godot_validate_scene_load`. Carry: add a bare `ERROR:`/runtime marker to the verdict once probes execute code.
4. **Phase 8 — Feature H: scene authoring** (gated on Phases 1, 6, and `validate_scene_load`). Done = 5 bridge mutation cmds + undo + reload-check + a provable-rollback test.
5. **Portability + CI batch** (audit bucket D; parked — moves up if external users become a goal). Done = `setup.ps1` works on stock PS 5.1 (D1), unix installs persist the located Godot (D2), no hardcoded capsulecastle default (D3), windows CI leg + pinned dev deps (D6), tests for the zero-coverage modules (D7). First action: spike D1/D2 on a clean VM or fresh user account.

## Quick fixes (clear in one pass)

Small, self-contained chores that need no plan and aren't worth their own thread. Capped at 5 — overflow means clear some or promote one out, so this stays a batch and never a second backlog. Add with `/claudhd:quick <text>`, clear them in one focused pass with `/claudhd:quick`. The active thread has right of way: clear these between threads, not mid-thread. A fix that turns out to need real thinking gets kicked back to IDEAS.md.

(nothing queued yet)

## Idea flow (do not open a new chat)

New idea mid-task: `/claudhd:idea <text>` records it in IDEAS.md so you can keep working. `/claudhd:harvest` backfills ideas from past sessions you never recorded. `/claudhd:triage` clears the inbox. Finished work is recorded in SHIPPED.md via `/claudhd:shipped`.

## Loose ends

- **F-10 housekeeping:** `docs/CURRENTNESS_AUDIT.md` + `docs/RUNTIME_VERIFICATION_QUEUE.md` are untracked gantry placeholders (still `<DATE>`/`<path>`) — fill or remove before they rot. These are the only untracked files in the tree.
- **SHIPPED.md** is current through Phase 4; update it as later phases land (or via `/claudhd:shipped`).

## Leaving this file when you stop

Before you walk away, or whenever you switch context, make the "Next physical action" line true and tiny. That one line is what lets you stop mid-thought and lose nothing. The quick way: run `/claudhd:wrap` and it reconciles this file for you - checks off what's done, writes the next action, and closes out loose ends.
