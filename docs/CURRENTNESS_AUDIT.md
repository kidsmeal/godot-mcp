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
