# /yoke implement phase 4 — the review loop and the handoff

Read this when coding and self-verification are complete and every
acceptance-criterion QA run is recorded
([`implementing/test-and-record.md`](implementing/test-and-record.md)), or when
re-entry lands in the review stage.

## Status writes inside the segment

Every status write in this segment uses `lifecycle.transition.execute` with
the next stage of the pinned definition as its target:

```text
yoke lifecycle transition PREFIX-N --from <live-stage> --to <next-stage> --reason "Implementation review"
```

The transition enforces the pinned target's gates and emits lifecycle events.
Before transitioning, commit every review-loop fix in `WORKTREE_PATH`, new
files included, and refresh all affected QA cases against that committed tree
through [`implementing/test-and-record.md`](implementing/test-and-record.md).
Materialize plans attached at the target with `yoke qa plan materialize --item
PREFIX-N --transition <next-stage>` and execute unsatisfied cases with `yoke
qa case run --requirement-id <id>`. Browser cases must serve that commit and
name its expected branch and SHA. A capture alone is not a passing verdict.
Before committing, run the source-dev stale-string check:
`python3 -m yoke_core.domain.stale_string_audit verify PREFIX-N "$WORKTREE_PATH"`.
A failure blocks the commit: fix the reported strings, then rerun the audit. Never substitute scalar status writes for the transition.

## The loop

1. **Enter review.** Write the stage after the implementation stage (for an
   issue, `reviewing-implementation`). The session keeps its claim; this is
   still implementation work in the same lane, not a checkpoint.
2. **Review in place.** Review the branch against the spec and every
   acceptance criterion. Fix what the review finds in the same lane, re-run
   the relevant verification, and refresh the QA evidence.
3. **Hand off.** When review actually passes, write the binding's
   `through_stage_id` (for an issue, `reviewed-implementation`). Only after
   that transition succeeds, release the item claim:

   ```text
   yoke claims work release --item PREFIX-N --reason implementation-handoff
   ```

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
