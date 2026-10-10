# Refine — Claim, Enter, Gather

## 1b. Claim before status or artifact work

The supported pin is resolved first. At REFINE_SOURCE_STATUS, enter
REFINE_ACTIVE_STATUS; at the active stage resume without a no-op transition.
Other stages were rejected by the context interpreter.

```bash
yoke sessions touch --mode refine
yoke claims work acquire --item "$ITEM_REF" --reason refine_run
```

`claims.work.acquire` resolves ambient session authority. Stop on conflict.
For item_artifact scope at source entry only, run the pre-handoff readiness
gate **before** transition. Read [`readiness-repair.md`](readiness-repair.md):
pure_stale_count is repaired with the claim held; recoverable coverage gaps
continue through critique, while unrecoverable/unavailable branches checkpoint
and release as taught there. Checks follow independent effective axes; parity
applies only when both are enabled.

Then use `lifecycle.transition.execute` with source/active statuses:
```bash
yoke lifecycle transition "$ITEM_REF" --from "$REFINE_SOURCE_STATUS" --to "$REFINE_ACTIVE_STATUS" --reason "Refinement started"
```
Skip this command on active-stage re-entry.

## 2. Gather applicable artifacts

Read named structured fields; use rendered body only when no substantive
structured artifact supplies the intended content:
```bash
yoke items get "$ITEM_REF" spec
yoke items get "$ITEM_REF" design_spec
yoke items get "$ITEM_REF" technical_plan
```

Only generated-task-plan scope reads graph-authoritative fields and tasks:
```bash
yoke items get "$ITEM_REF" worktree_plan
yoke items get "$ITEM_REF" shepherd_caveats
yoke epic-tasks list --epic "$ITEM_REF"
```

Fallback:
```bash
yoke items get "$ITEM_REF" body
```

Empty fields are normal; failed reads halt rather than masquerading as empty.
If all applicable content is sparse, advise populating its missing structured
artifacts through the pinned authoring segment, then proceed with useful
structural additions. Continue with [survey-and-focus.md](survey-and-focus.md).
