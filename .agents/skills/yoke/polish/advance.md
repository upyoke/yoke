# Polish — Complete The Bound Segment

Covers polish steps 10 through 15: rerun attached QA cases, capture the final
summary, advance status, release the claim, emit the final output, and confirm
completion.

**Context variables** (set by earlier phases): `ITEM_REF`, `ITEM_NUM`,
`WORKTREE_PATH`, `WORKTREE_PATHS`, `POLISH_THROUGH_STAGE`, `LIVE_STAGE`,
`NEXT_STAGE`.

---

## 10. Inspect Outstanding QA Requirements (read-only)

Refresh `yoke workflows item get ITEM --json` and read its exact pin with
`yoke workflows version get WORKFLOW VERSION --json`. Set `LIVE_STAGE` to
the returned status and require the half-open `definition.skill_bindings`
interval containing it to belong to `polish`. Retain its `through_stage_id`
as `POLISH_THROUGH_STAGE`.

Set `NEXT_STAGE` to the unique forward target in `definition.transitions`
whose `from_stage_id` equals `LIVE_STAGE`, ordered by `definition.stages`
to exclude rework edges. It must stay inside the interval or equal its
handoff boundary. If no unique edge exists, stop with
`workflow_next_stage_ambiguous`; if it skips the boundary, stop with
`polish_segment_invalid`. Name the live stage and ask the workflow owner
to repair or select a declared route. Never choose a literal target.

Inspect outstanding QA evidence for that target:

```bash
yoke qa gate-summary --item "$ITEM_REF" --target "$NEXT_STAGE"
```

The target is definition-derived. Do not compose raw `qa_requirements` SQL
during polish — `qa.gate_summary.run` is the canonical typed diagnostic.

## 10b. Re-run Attached Cases

Materialize and list cases for `NEXT_STAGE`:

```text
yoke qa plan materialize --item "$ITEM_REF" --transition "$NEXT_STAGE" --json
yoke qa requirement list --item "$ITEM_REF" --json
```

Run every outstanding, non-waived case bound to that target through its
registered runner. For Browser methods, execute the ordered plan against
a target serving the committed lane, with current branch/SHA freshness:

```text
yoke qa plan run --item "$ITEM_REF" --transition "$NEXT_STAGE" --base-url <candidate-url> --expected-branch <lane-branch> --expected-sha <lane-head-sha>
```

For targeted recovery, use `yoke qa case run --requirement-id <id>`.
Follow the runner's returned review dispatch and submission recipe;
pending review is not a pass. Delivery cases belong to the definition's
delivery stages outside the polish interval; do not pull them forward.

If any case blocks, leave the item at `LIVE_STAGE` and report the
failed requirement/run instead of advancing.

## 11. Capture Final Summary

Before status advancement, capture the details you will present after cleanup is finished. Do not emit the success summary yet:

```
## Polish Complete — PREFIX-{N}

**Worktree:** {WORKTREE_PATH}
**Worktree lanes:** {WORKTREE_PATHS}
**Files changed:** {count} ({list})
**Tests:** {pass/fail/not configured}
**Commit:** {hash or "no changes needed"}

{Brief summary of what was fixed and why}
```

## 12. Transition To The Bound Handoff

After all polish work is committed and verification passes, take the
declared edge through `lifecycle.transition.execute`, which runs the
target gates and syncs GitHub:

```bash
yoke lifecycle transition "$ITEM_REF" --from "$LIVE_STAGE" --to "$NEXT_STAGE" --reason "Polish verified"
```

Refresh the pin after success. If its status is still inside the polish
interval, repeat steps 10–12 for the next declared edge, including its
target's QA. Stop immediately when status equals `POLISH_THROUGH_STAGE`.
Do not cross it under this command or repeat a transition already recorded.

Final output should name the actual stage reached:
> **PREFIX-{N}** polished: `{entry working stage}` -> `{POLISH_THROUGH_STAGE}`
> Next bound skill: `/yoke {NEXT_SKILL_ID} {ITEM_REF}`.

Resolve `NEXT_SKILL_ID` from a fresh item detail read using
[the shared handoff recipe](../shared/stage-handoff.md).

`POLISH_THROUGH_STAGE` is a hard handoff point for this command. Do **not** continue
into merge, PR creation, or deployment from the polish flow. The next bound
skill begins through its fresh command entrypoint.

**If any step above failed or tests are failing:** Do not advance. Leave
the item at its current working stage and report the failed gate and repair.

Function-call equivalent (the CLI above builds this envelope internally):

```jsonc
{
  "function": "lifecycle.transition.execute",
  "actor": {"session_id": "<this-session>"},
  "target": {"kind": "item", "item_id": $ITEM_NUM, "public_ref": "$ITEM_REF"},
  "intent": "polish_complete",
  "payload": {"source_status": "$LIVE_STAGE", "target_status": "$NEXT_STAGE"},
  "options": {"sync_github_body": true}
}
```

## 13. Release Item Claim

Release the exclusive work claim before any success output is emitted. Successful polish is not complete while the session still owns `$ITEM_REF`.

```bash
yoke claims work release \
    --item "$ITEM_REF" \
    --reason completed
```

**Important:** This MUST run before the final operator summary. A release failure surfaces in the CLI output and must still be called out in the final report.

Function-call equivalent (for dispatch-surface callers — the CLI above builds this envelope internally):

```jsonc
{
  "function": "claims.work.release",
  "actor": {"session_id": "<this-session>"},
  "target": {"kind": "claim", "claim_id": <claim_id>},
  "intent": "polish_complete",
  "payload": {"claim_id": <claim_id>, "reason": "completed"}
}
```

## 14. Final Output

After status advancement and claim release, emit:

```
## Polish Complete — PREFIX-{N}

**Worktree:** {WORKTREE_PATH}
**Worktree lanes:** {WORKTREE_PATHS}
**Files changed:** {count} ({list})
**Tests:** {pass/fail/not configured}
**Commit:** {hash or "no changes needed"}

{Brief summary of what was fixed and why}
```

Include the status transition note from step 12 in this final output.

## 15. Completion

Polish is complete when:
- All changed files have been reviewed against ACs
- Identified issues have been fixed
- Tests pass (or are not configured)
- Changes are committed (or none were needed)
- Status has reached `POLISH_THROUGH_STAGE` from the pinned binding
- The item claim has been released with reason `completed`
- The final report names the resolved worktree path or worktree lane set and the verification that ran
- The operator has been shown what changed in the final output
- The polish flow has stopped at its bound handoff without merge or delivery steps

Polish is NOT complete if:
- The worktree is in a failing test state — fix before reporting
- The operator interrupted with a question — answer it before continuing

Status advancement is handled in step 12. Claim release is handled in step 13, and the final operator output happens in step 14.
