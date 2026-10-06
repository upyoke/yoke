# /yoke implement phase 4 — the review loop and the handoff

Read this when coding and self-verification are complete and every
acceptance-criterion QA run is recorded
([`implementing/test-and-record.md`](implementing/test-and-record.md)), or when
re-entry lands in the review stage.

## Status writes inside the segment

Every status write in this segment goes through the internal advance sub-skill
with the next stage of the pinned definition as its target:

```text
/yoke advance PREFIX-N <next-stage>
```

That sub-skill runs the target stage's preflight gates, the stale-string audit
on review targets, browser QA and project E2E where the target needs them, and
the worktree-scoped commit (`git -C "$WORKTREE_PATH" add -A`) before the
status write, so review-loop fixes — new files included — land with the
transition and the lane is never left dirty. Never write a status directly
(`items scalar update`, raw `lifecycle transition` without those phases):
direct writes skip the claim handoff, the worktree-scoped commit, and the
lifecycle events.

## The loop

1. **Enter review.** Write the stage after the implementation stage (for an
   issue, `reviewing-implementation`). The session keeps its claim; this is
   still implementation work in the same lane, not a checkpoint.
2. **Review in place.** Review the branch against the spec and every
   acceptance criterion. Fix what the review finds in the same lane, re-run
   the relevant verification, and refresh the QA evidence.
3. **Hand off.** When review actually passes, write the binding's
   `through_stage_id` (for an issue, `reviewed-implementation`). Its finalize
   releases the claim with the handoff reason.

Do not pause for operator confirmation between these steps, and do not skip
from the review stage straight to any stage past the handoff.

**A test pass is not gate satisfaction.** Green tests mean the implementation
behaves; the handoff stage's QA gate separately requires every blocking
`qa_requirements` row to have a passing run. Summarize a green suite as "tests
pass", never "all gates pass", until the handoff write completes. Preview the
gate with `yoke qa gate-summary --item PREFIX-N --target <handoff-stage>`.

## At the handoff

The binding's `through_stage_id` is a fresh command and claim boundary. Stop
the skill there: do not start the next segment's work from this session's
flow, because that skill claims the item itself. Report the transition, then
render the handoff from the definition rather than naming a skill from memory:

```text
yoke workflows item get PREFIX-N
```

Its `next_skill_id` names the skill bound at the new live stage. Report:

> **PREFIX-N** (`<title>`): `<review stage>` → `<handoff stage>`; next bound skill: `<next_skill_id>`.

Ending a turn sends no Fleet message. Reach the seat holding this item's scope
deliberately with `yoke say --steering` when it must act. Send before
releasing a claim still held; after the handoff release the address falls back
to the item last held.
