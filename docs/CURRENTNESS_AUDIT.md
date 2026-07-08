# Currentness Audit

Last updated: <DATE>

Purpose: help a future session answer "what is actually current?" before touching an old
plan. This is an audit snapshot, not a reorganization. Prefer correcting this file over
rewriting or moving the older docs. Refresh it with `/gantry:audit`.

## Trust First

The best current anchors. A session can rely on these.

| Area | Current anchor | Current read |
|---|---|---|
| Active implementation | `<path>` | <what is live, which phases landed, what is in flight> |
| Codebase lookup | `<path>` | <the map that is most current; may lag on fine detail> |
| Conventions / rules | `<path>` | <the authoritative style/design rules - reference, not a task queue> |
| Runtime verification | `RUNTIME_VERIFICATION_QUEUE.md` | <live list of shipped-but-unverified systems> |
| Durable memory | `<path>` | <preferences / long-range intent - not a build queue> |

## Needs Reconciliation

Docs or systems with mixed signals. Name the stale claim and what the code actually shows.

### <Doc or system>
<what it claims> vs <what the code evidence shows>. Read as: <how to treat it until reconciled>.

## Likely Shipped / Historical

Should not pull attention unless a bug points back here.

| Area | Read |
|---|---|
| <area> | <shipped / archived - keep as history> |

## Rule of thumb
- Roadmap says what to do next.
- Plans say how to do it.
- Design says why it exists and what constraints it obeys.
- Archive says what happened.
- Memory says what must not be forgotten.

## Deferred review notes
- [x] `tests/test_procgen_biome_config.py` + `tests/test_procgen_biome_build.py`: codex phase-reviewer's sandbox cannot execute `.venv/Scripts/python.exe` ("Access is denied"), so it could not run the named pytest command — verification was static-read only (phase 1, biome-world plan). RESOLVED out-of-band: orchestrator re-ran locally, `21 passed`, plus full suite `489 passed / 7 skipped`, `ruff`, `mypy`, and `ci_smoke` all green.
- [x] Same codex venv-execution limitation recurred on phase 2 (biome-world plan), raised there as a fix-now note ("rerun the named command where the venv is executable"). RESOLVED out-of-band before the review was invoked: orchestrator re-ran locally — full suite `499 passed / 7 skipped`, `ruff` clean, `mypy` clean, `ci_smoke ALL PASS`. This is a standing property of the codex backend, not a per-phase defect; every codex review in this repo is static-read only and its gates must be re-run locally.
- [x] Recurred again on phase 3 (biome-world plan), same fix-now note. RESOLVED: orchestrator re-ran locally — `tests/test_procgen_biome_audit.py` `2 passed`, full suite `501 passed / 7 skipped`, `ruff` clean, `mypy` clean, `ci_smoke ALL PASS`.
