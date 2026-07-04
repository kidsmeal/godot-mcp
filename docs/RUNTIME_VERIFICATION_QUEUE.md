# Runtime Verification Queue

Last updated: <DATE>

The live list of systems that are code-complete or mostly shipped but still need real-run
confidence. Keep code/test facts separate from the manual check still owed, so stale TODOs
are easy to retire. Curate with `/gantry:verify`.

---

## Active checks

### 1. <System name>

**Why:** <why this still needs a real run even though the code/tests pass.>

**Code checks already done:**
- <provably wired fact - file/symbol that exists and is referenced.>
- <automated coverage, if any: test file name.>

**Manual check:**
- <exact step.> <pass condition - what you should observe.>
- <exact step.> <pass condition.>

**Close when:** <the precise condition that lets this item be retired - then say what doc, if any, gets archived.>

---

## Closed / stale items

- <item> - closed: <evidence it is done, e.g. code inspection / regression test / in-engine verification recorded>.
