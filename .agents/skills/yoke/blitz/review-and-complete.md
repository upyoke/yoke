# Blitz — whole review and document completion

## 6. Review all integrated slices

Inspect landed diffs/current product end to end; run the full relevant
registered suite and applicable user-facing proof; confirm governed migration
and delivery receipts; remove replaced paths; reconcile every Slice Log entry.

Refresh before the once-per-item close and each later transition. The pin lookup
is `yoke workflows version get WORKFLOW_ID WORKFLOW_VERSION --json`:

```sh
yoke workflows item get ITEM --json
yoke workflows version get <workflow-id> <workflow-version> --json
```

Set `LIVE_STAGE` from status and `NEXT_STAGE` from the unique forward
`definition.transitions` edge whose `from_stage_id` matches it, ordered by
`definition.stages`. Confirm the active half-open binding owns Blitz.
At its boundary report rendered `next_skill_id`. Absent/ambiguous edge is
`workflow_next_stage_ambiguous`: owner repairs/selects a declared route.

```sh
yoke lifecycle transition ITEM --from LIVE_STAGE --to NEXT_STAGE --reason "All slices integrated; final reconciliation started"
```

## 7. Reconcile the document; close one edge at a time

Revise the linked document with this exact completion shape:

```markdown
## Blitz Completion

- Completed: <what was completed: delivered outcomes>
- Changed: <what changed from the starting plan, or none>
- Remaining: <what remains: open work, or nothing>
- Verification identities: <commands, receipts, runs, commits, or artifacts>
- Parent reconciliation: <how the parent strategy was reconciled, its revision, or no parent exists>
```

Append final Slice Log with document revision/final verification. Re-read
`yoke strategy execution get ITEM --json` to confirm this item's document claim.
Refresh status/pin and resolve each unique forward edge as above until
`definition.terminal_stage_ids`; advance one declared stage at a time:

```sh
yoke lifecycle transition ITEM --from LIVE_STAGE --to NEXT_STAGE --reason "Execution document reconciled with passing evidence"
```

When release still owes selected-flow delivery, keep the work claim and park this session.
Its delivery wake resumes the same definition-driven walk.
The terminal edge still runs `doc_completion` and document-archive semantics.

The terminal transition atomically archives the linked execution document only when no other
non-terminal Blitz links it, and releases the item-owned document claim and all
registered Blitz lanes. Already archived is a no-op; a shared live document stays active;
the parent document is never archived here. Archive failure
`GATE_BLITZ_DOCUMENT_ARCHIVE_FAILED` retains stage and names retry recovery.
Use that recovery, rather than manual archival. After terminal success:

```sh
yoke claims work release --item ITEM --reason "Blitz completed"
```

Blocked completion retains current stage: record the missing fact in
`Live Status`, repair document/evidence and preserve the completion gate.
