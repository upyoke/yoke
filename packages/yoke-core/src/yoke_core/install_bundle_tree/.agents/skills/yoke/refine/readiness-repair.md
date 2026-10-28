# Refine — Readiness Repair

`classify_readiness_issues` sorts the payload's issues:
- pure_stale_count (all STALE_LINE_COUNT): repair-stale-count, rerun.
- recoverable (FILE_BUDGET_NOT_IN_CLAIM, CLAIM_NOT_IN_FILE_BUDGET):
  repair-claim-coverage, then continuing into refine critique.
- SCOPED_PATH_NOT_IN_FILE_BUDGET (alone or with the codes above): paste
  each remediation row into the File Budget, widen claims if on, rerun.
- unrecoverable: checkpoint, release `readiness-check-blocked`, exit 1.
- unavailable: same, releasing `readiness-validation-unavailable`; no retry.
- cross_item_overlap: classify per [path-claim-blocking.md](../idea/path-claim-blocking.md).
```bash
yoke readiness repair-stale-count --item "$ITEM_REF"
yoke readiness repair-claim-coverage --item "$ITEM_REF"
yoke sessions checkpoint --step 1 --action refine --chainable false --outcome blocked --item "$ITEM_REF"
yoke claims work release --item "$ITEM_REF" --reason "readiness-check-blocked"
```
The work claim stays held on repair; rerun readiness after.
