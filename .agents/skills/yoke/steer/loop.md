# /yoke steer — standing loop

Run this loop after the steering-scope claim and the strategy-doc lock are
held. No new scheduler: each pass is a message-wake or a periodic frontier
check. Keep the claimed document current on every material change.

Do not invoke `/yoke feed`.

## Wake sources

- A delivered session message (acknowledge first, then act).
- A periodic frontier check when no message is waiting.

Stamp `yoke sessions touch --mode steer` at the start of each pass if the
mode is no longer `steer`.

## Pass

### 1. Read the scope frontier

```text
yoke charge schedule --project {_project} --json
yoke claims steering list --project {_project} --active-only --json
```

`charge.schedule` is a frontier **read**. It does not dispatch and it is
not feed. Record runnable unclaimed items, dependency gates, and anything
already claimed. Write material frontier movement into the doc (step 6).

### 2. Consume worker reports

```text
yoke messages list --json
```

For each authenticated inbound message: acknowledge immediately, then
apply only what the report justifies.

```text
yoke messages acknowledge MESSAGE-ID
```

Typical report body: `DONE PREFIX-N <one-line summary>`. When a
steering-scoped item is `done` and the report is enough:

1. Update item state, dependencies, or gates through the registered item
   surfaces the report actually requires — never invent a status change.
2. Follow [`worker-lifecycle.md`](worker-lifecycle.md) rule 5: terminate
   that worker. No lingering. No re-tasking.
3. Write the close-out into the doc.

### 3. Work the strategy document itemless

```text
yoke strategy doc get {SLUG} --project {_project}
```

The coordinator holds no work item. Plan-level progress lives in the
claimed doc: objective, frontier, decisions, gates, dead ends. Edit
through the registered strategy surfaces (`strategy.doc.get`,
`strategy render`, `strategy ingest` / `strategy.doc.replace`). The doc
plus the items survive coordinator death.

### 4. Hand a chunk to an executor

When a chunk of the doc needs an implementer:

1. File a Blitz from the doc (`/yoke idea --workflow blitz "{title}"`).
   Link it before anyone claims it:

   ```text
   yoke strategy execution link ITEM --slug {SLUG} --project {_project}
   ```

2. **Release the document lock** so the worker can claim the Blitz. A
   session-held lock and a live Blitz on the same slug are mutually exclusive
   — leaving the lock held is a handoff defect.

   ```text
   yoke strategy doc-claim release {SLUG} --project {_project} --reason "blitz-handoff"
   ```

3. Encode `item_dependencies` edges (or an explicit no-edges attestation
   on the filed items) in the same action that files a related batch.
   Title-only batches that are already claimable are a defect.

4. Launch per [`worker-lifecycle.md`](worker-lifecycle.md). After the
   Blitz reaches `done`, re-acquire the document lock if this coordinator
   is still steering the slug.

### 5. Staff unpicked runnable work

When runnable work sits unclaimed, invoke the steering backstop — not a
hand-rolled spawn, and not `/yoke do`:

```text
yoke steering backstop evaluate --project {_project}
```

The backstop launches only work the scheduler already calls runnable that
carries no live work claim and has waited past the project's unpicked
grace. It refuses callers who do not hold the steering-scope claim. Use
`--dry-run` only to inspect; a live pass files the launches.

Prompt launches for newly runnable unclaimed items follow
[`worker-lifecycle.md`](worker-lifecycle.md) (keep the frontier maxed
out). The backstop is the safety net for work that sat.

### 6. Keep the document current

After every material change — frontier movement, gate decision, launch,
escalation, dead end, report close-out — write it into the claimed doc
through the registered strategy surfaces. The doc is coordinator state,
not a wrapup artifact.

### 7. Escalate only human decisions

Escalate to the operator when the loop cannot choose: conflicting
reports, a scope that needs a new project, a lock it cannot release
without destroying in-flight work, or any decision the operator reserved.
Present the decision, the evidence, and the recommended option, then
**wait**. Do not guess. Do not implement. Do not file a substitute item
to dodge the gate.

Everything else continues autonomously.

## Stop

A clean stop is wrapup in `SKILL.md` step 5: release the document lock
and the steering-scope claim. An abandoned coordinator is reclaimed by
the stale sweep; do not treat that as a successful wrapup.
