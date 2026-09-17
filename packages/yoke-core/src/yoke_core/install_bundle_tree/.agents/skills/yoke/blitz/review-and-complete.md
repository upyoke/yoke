# /yoke blitz steps 6–7 — review the execution and complete the document

## 6. Review the whole execution

After the last slice is integrated:

- inspect all landed diffs and the current product path end to end;
- run the full relevant registered suite plus user-facing proof where
  applicable;
- confirm all governed migrations and delivery runs have evidence;
- remove obsolete paths the plan replaced;
- reconcile the execution document against every Slice Log checkpoint.

Transition into the once-per-item close:

```text
yoke lifecycle transition ITEM --from implementing --to reviewing-implementation --reason "All slices integrated; final reconciliation started"
```

## 7. Complete the document and close

Revise the linked strategy document so it explicitly records:

- what was completed;
- what changed from the starting plan;
- what remains, including an explicit statement when nothing remains;
- verification and delivery evidence with stable identities;
- how the parent strategy was reconciled, or that no parent exists.

Use this exact document-owned closeout shape so the completion gate can
distinguish terminal evidence from planning prose:

```markdown
## Blitz Completion

- Completed: <delivered outcomes>
- Changed: <departures from the starting plan, or none>
- Remaining: <open work, or nothing remains>
- Verification identities: <commands, receipts, runs, commits, or artifacts>
- Parent reconciliation: <parent update and revision, or no parent exists>
```

Append a final Slice Log entry naming the document revision and the final
verification result. Re-read `yoke strategy execution get ITEM --json` and
confirm the document claim still belongs to this item.

Transition through the `doc_completion` gate:

```text
yoke lifecycle transition ITEM --from reviewing-implementation --to done --reason "Execution document reconciled with passing evidence"
```

The terminal transition atomically archives the linked execution document
when no other non-terminal Blitz still links it, then releases the item-owned
document claim and every registered Blitz worktree lane. An already-archived
document is a no-op; a shared live document stays active; and the parent
document is never archived by this path. If the archive write fails,
`GATE_BLITZ_DOCUMENT_ARCHIVE_FAILED` keeps the item at
`reviewing-implementation` and names the retry recovery. Do not archive the
document by hand after completion. Release the remaining session work claim:

```text
yoke claims work release --item ITEM --reason "Blitz completed"
```

If completion is blocked, keep the item at
`reviewing-implementation`, record the missing fact in `Live Status`, and
repair the document or evidence. Never weaken the completion gate.
