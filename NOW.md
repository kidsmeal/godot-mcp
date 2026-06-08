# NOW (read me first)

<!-- claudhd: opt-in marker (do not remove) - ClauDHD's hooks only act on a NOW.md that has this line -->

One active thread at a time. This file is the cursor: what is live, the next physical action, and what is queued behind it. Read it first, update it as you go.

_Committed, so it follows your branch: `git checkout` swaps this cursor to that branch's thread._

Last touched: 2026-06-07

## Active thread (only one)

**Feature Batch F–H — gated Gantry pipeline (correctness-first hardening → features)**

Phases 1–4 shipped: containment, validator-harness leak fix, engine-grounding correctness, profile robustness, + ruff/mypy/CI. 99 tests green; `main` == `origin/main` (last: `bbf5df8`, Phase 4). Plan: `docs/design/feature-batch-fgh.plan.md`. Loop per phase: implementer → phase-reviewer → fix/re-review → commit + push (human-gated at each commit).

Next physical action:

- [ ] Launch the **Phase 5** implementer — *Feature F: grounding surfaces* (`project_input_actions` + `ui_*` typo-lint, `project_setting`, `project_classes`, `project_layers`, + the carried `lint.py:242` `re.error` guard), per the plan. Offline-testable; biggest phase so far.

Rule: when you finish a step, check it off and write the next single tiny step. Do not start another thread until this one ships or you consciously move it to the Queue.

## Queue (in order, not now)

What is eligible to become active next, in order. Items clear triage's readiness gate before they land here: each is either a ready task (carries a one-line "done" + first action) or a spike (the unknown to resolve before it can be built). Nothing queues as a bare one-liner.

1. **Phase 6 — Bridge hardening** (prereq for G/H). Done = per-client TCP buffers/framing + distinct `protocol`/`bridge_version` field in `ping` + a doctor check. First action: implementer on Phase 6 per the plan.
2. **Phase 7 — Feature G: runtime loop**. Done = `godot_run_game_headless` (+ empirical `--quit-after` exit-code check) + `godot_screenshot` (editor viewport) + `godot_validate_scene_load`. Carry: add a bare `ERROR:`/runtime marker to the verdict once probes execute code.
3. **Phase 8 — Feature H: scene authoring** (gated on Phases 1, 6, and `validate_scene_load`). Done = 5 bridge mutation cmds + undo + reload-check + a provable-rollback test.

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
