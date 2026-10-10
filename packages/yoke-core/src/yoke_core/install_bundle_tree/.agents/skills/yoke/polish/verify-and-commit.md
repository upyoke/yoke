# Polish — Verify And Commit

## 8. Verification authority

Read the exact pinned definition. Derive `REVIEW_STAGE` from the unique forward
implementing-bucket to reviewing-bucket edge at/before `POLISH_ENTRY_STAGE`.
This is review-plan attachment, not polish completion; never move backward.

```python
stages = {stage["id"]: stage for stage in definition["stages"]}
order = {stage["id"]: index for index, stage in enumerate(definition["stages"])}
review_targets = {
    edge["to_stage_id"]
    for edge in definition["transitions"]
    if stages[edge["from_stage_id"]]["board_bucket"] == "implementing"
    and stages[edge["to_stage_id"]]["board_bucket"] == "reviewing"
    and order[edge["from_stage_id"]] < order[edge["to_stage_id"]]
    <= order[POLISH_ENTRY_STAGE]
}
if len(review_targets) != 1:
    raise SystemExit(
        "polish_review_transition_ambiguous: expected one implementation review entry; "
        "ask the workflow owner to repair or select the declared review route"
    )
REVIEW_STAGE = next(iter(review_targets))
```

Materialize **all** effective default/item review plans and list requirements:
```bash
yoke qa plan materialize --item "$ITEM_REF" --transition "$REVIEW_STAGE" --json
yoke qa requirement list --item "$ITEM_REF" --json
```

Every nonwaived Command requirement whose latest pass does not prove current
committed HEAD must run, including **previously satisfied** cases made stale
by fixes. For multi-lane work, prove every changed lane through its task
requirements; a parent lane is insufficient. Without a project plan, record
the relevant changed tests against the item's AC-derived requirement.
Explicitly rerun changed tests even when a broader case passes. Prompt or
large-script changes also need relevant invariants/doctor:
```bash
yoke watch doctor -- --quick
```

While fixing, use failing tests, changed module paths or
`yoke watch pytest --impacted main --bounded`. Unbounded selection is reported,
not silently widened. A CI-configured project runs the pushed committed lane
through its watcher; commit before CI. `--local` is only a small check expected
within about one minute; an overlong local check is interrupted cleanly with
its incomplete capture preserved, then committed and continued on CI.

**The registered QA case is the one full execution.** Do not rediscover its
command or run a manual full sweep before executing the same tree again:
```bash
yoke qa case run --requirement-id <requirement-id>
```

It resolves the lane, streams output, prints its raw capture path, records
verdict and stores complete output. Continue yielded handles to exit; do not
launch another copy. Persist that complete capture on **this** item:
```bash
yoke items structured-field replace "$ITEM_REF" --field test_results --stdin < CAPTURE_PATH
```

A `command-ci` run's `verification_tree.head_sha` and conclusion prove the
candidate; the completion gate accepts that recorded verdict without a
hand-fetched pytest banner.

**Current-item failures belong here.** Future/planned item ownership or a
planned path claim is not a waiver. Widen required scope with
`claims.path.widen` (operator/debug alias `path-claim-widen`) and use
dependency or claim reconciliation before retrying.
Do not use `path-claim-override` for a planned future claim when reconciliation
works; override is last resort for irreducible live collisions and needs
explicit operator approval. Do not leave the worktree in a failing state.

## 9. Commit and prove the final head

Commit specific changed files in each changed lane; leave untouched lanes and
unrelated dirty work alone:
```bash
git -C "<absolute-lane-path>" add <specific-changed-files>
git -C "<absolute-lane-path>" commit -m "polish: <finishing-fix-purpose>"
```

No changes means no commit. Never push or create a PR by hand; registered CI
owns publication. Resolve full commit identities with rev-parse and verify
them, rather than expanding a short hash.

After the commit, run every required case whose evidence is stale against
the committed HEAD. A changed tree requires rerun; unchanged proven trees
do not need duplicate full execution. **Make no further commits after the
final passing execution.** Any later change restarts exact-head verification.
Proceed to [advance.md](advance.md).
