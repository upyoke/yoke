# Polish — Verify And Commit

Covers polish steps 8 and 9: run verification against the fixes, then commit.

**Context variables** (set by earlier phases): `ITEM_REF`, `ITEM_NUM`, `WORKTREE_PATH`,
`WORKTREE_PATHS`.

---

## 8. Run Verification

Materialize the project-default and item-attached plans for the workflow's
review transition:

```bash
yoke qa plan materialize \
  --item "PREFIX-{N}" \
  --transition reviewing-implementation \
  --json
yoke qa requirement list --item "PREFIX-{N}" --json
```

Select unsatisfied, non-waived plan-materialized requirements for that
transition. Execute each `Command` case through its registered runner:

```bash
yoke qa case run --requirement-id <requirement-id>
```

The case runner resolves the item's worktree, streams the command's output
live to stderr while capturing it, records the verdict, and stores the
complete command output as a QA artifact. It names its raw capture file
before the command starts (`capture=...` on stderr), so a long case is
followable without a second copy of the run.

When a Command case passes, persist that capture onto **this** item so the
polish evidence gate reads this row's `items.test_results` rather than an
empty field (or another item's row):

```bash
yoke items structured-field replace "$ITEM_REF" --field test_results --stdin < CAPTURE_PATH
```

`CAPTURE_PATH` is the file named by the case runner's `capture=` line. Use
the registered replace adapter; do not skip this write because a later
usher/merge gate can also read the field.

A CI-routed Command case (`command-ci`) already records `verification_tree.head_sha`
and a conclusion on the run. The polish→implemented gate accepts that recorded
verdict without a hand-fetched pytest banner in `items.test_results`.

**This is the one full execution.** Iterate with the cheap layers while
fixing — the individual failing tests, the changed module's paths,
`yoke watch pytest --impacted main --bounded` (which reports an unbounded
selection instead of widening to the full sweep, and which runs on the
project's CI against the pushed lane commit when the project declares a
`ci_workflow_file` capability — commit before running it, or pass `--local`
to run it here) — then let the case run close the loop.
Do not run the project's full sweep by hand and then re-execute the same
tree through QA: the case executor re-runs the identical registered
command, so only the verdict-producing run needs to happen. Do not
rediscover a command from project settings and do not write a duplicate run
manually.

Verification expectations:

- Run every attached `Command` case that gates review. A project may attach
  more than one plan at the transition.
- For a multi-worktree epic, verify every changed lane through the epic's task
  requirements; do not pretend the parent item's one worktree covers them.
- If no project plan is attached, run the most relevant changed tests directly
  in the worktree and record them against the item's AC-derived requirement.
- When tests themselves change, rerun those tests explicitly even if a broader
  Command case also passes.
- When prompt surfaces or large scripts change, run the relevant doctor or
  invariant checks as additional proof. Invoke doctor through
  `yoke watch doctor -- --quick`.

If verification fails, investigate and fix it before continuing.
Future/planned item ownership or a planned path claim is not a waiver for a
current regression. When a required fix expands the file set, use
`claims.path.widen` (operator/debug fallback: `path-claim-widen`) and
dependency or claim reconciliation before retrying.
Do not use `path-claim-override` for a planned future claim when reconciliation can
resolve the ordering; override is last resort for irreducible live collisions
and requires explicit operator approval.
Do not leave the worktree in a failing state.

## 9. Commit

If files changed during polish, commit them with a descriptive message:

```bash
git -C "{worktree-path}" add {specific changed files}
git -C "{worktree-path}" commit -m "polish: {brief description of finishing fixes} (PREFIX-{N})"
```

Use a scoped `git add` containing only the files changed by this pass. For a
multi-worktree epic, commit each changed lane separately and leave untouched
lanes alone. If no changes were needed, skip the commit and report that the
implementation was already clean.

Do not push or create a pull request. Usher owns those actions.

After the commit, rerun each required Command case with the committed HEAD so
the latest requirement verdict and artifact prove the exact branch tip. That
is a changed tree, not a same-tree duplicate, so it is required rather than
wasteful. Make no further commits after that final passing execution.
