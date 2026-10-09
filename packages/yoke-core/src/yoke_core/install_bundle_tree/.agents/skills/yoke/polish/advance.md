# Polish — Complete The Bound Segment

## 10. Resolve the next declared edge

Refresh the item pin and exact version. The half-open
`definition.skill_bindings` interval containing `LIVE_STAGE` must belong to
polish; retain `POLISH_THROUGH_STAGE`. Use `definition.stages` order and
`definition.transitions` to select the unique forward `NEXT_STAGE`, excluding
rework. Require it inside the interval or equal to the boundary.

No unique edge is `workflow_next_stage_ambiguous`; a skipped boundary is
`polish_segment_invalid`. Name the stage/owner recovery and stop rather than
inventing a target. The typed QA gate-summary diagnostic supports only its
fixed enum targets: consult `yoke qa gate-summary --help` and use it only
when the actual target is accepted. Its read-only exit status is not passing
evidence. For other declared targets, inspect registered requirements and
let lifecycle gates enforce them; never pass arbitrary NEXT_STAGE to that
limited diagnostic or compose raw QA SQL.

## 10b. Prove target QA

```bash
yoke qa plan materialize --item "$ITEM_REF" --transition "$NEXT_STAGE" --json
yoke qa requirement list --item "$ITEM_REF" --json
```

Run every outstanding nonwaived case bound to this target through its runner.
Existing exact-head passes remain valid; stale evidence reruns. Browser
methods execute the ordered plan against a target serving the committed lane:
```bash
yoke qa plan run --item "$ITEM_REF" --transition "$NEXT_STAGE" --base-url <candidate-url> --expected-branch <lane-branch> --expected-sha <lane-head-sha>
yoke qa case run --requirement-id <requirement-id>
```

The case recipe is targeted recovery. Follow returned review dispatch and
submission instructions; pending review is not a pass. Delivery QA outside
this interval stays in delivery. A failed/blocked case leaves the item at
LIVE_STAGE; report its requirement/run and repair. No further commits after
the final passing execution.

## 11. Capture the report before advancing

Retain actual lanes, changed files, checks/verdicts, verified full commit or
no-changes result, and fix purpose. Do not emit success before cleanup.

## 12. Advance only through the pinned segment

`lifecycle.transition.execute` enforces target gates and GitHub synchronization:
```bash
yoke lifecycle transition "$ITEM_REF" --from "$LIVE_STAGE" --to "$NEXT_STAGE" --reason "Polish verified"
```

Refresh after success. If still inside the interval, **repeat steps 10–12**
for its next declared edge and target QA. Stop at `POLISH_THROUGH_STAGE`;
never repeat a completed transition or cross the boundary under polish.
A refusal leaves the actual working stage unchanged: report its gate/repair.

Resolve the next bound skill from a fresh read with the
[shared handoff recipe](../shared/stage-handoff.md). Merge, PR and deployment
belong to that fresh command, not this flow.

## 13. Release before success

```bash
yoke claims work release --item "$ITEM_REF" --reason completed
```

This is `claims.work.release`; use the actual claim identity returned by
acquisition when calling its typed dispatch surface. Success is incomplete
while this session owns the claim. Name any release failure in the final
report; never hide it behind a success summary.

## 14–15. Report and completion

After transition and release, report the actual lane set, changed files and
purpose, verification results, full verified commit/no changes, actual
entry-to-handoff transition and freshly resolved next skill.

Completion requires every changed lane/AC reviewed, findings fixed, required
checks passed (or explicitly unconfigured), committed/no changes, the pinned
boundary reached, claim released with completed reason, and report shown.
A failing tree is incomplete. A question midsequence is a checkpoint:
answer it before continuing. Stop at the handoff without merge/deploy.
