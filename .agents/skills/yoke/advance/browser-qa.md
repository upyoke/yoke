# Advance — Browser QA Execution Gate

Called at a workflow transition that has attached Browser-method cases. The
same flow executes both built-in methods:

- `browser-check`: assertions produce an automatic verdict.
- `browser-inspection`: capture produces evidence and a review request; a human
  resolves it to passed, failed, or waived.

The gate is re-entrant. Materialization is idempotent and rerunning a case
records a new run.

## 1. Materialize and select Browser cases

```bash
yoke qa plan materialize \
  --item "YOK-{N}" \
  --transition "{_target}" \
  --json
yoke qa requirement list --item "YOK-{N}" --json
```

Select unsatisfied, non-waived rows for this transition whose `method_id` is
`browser-check` or `browser-inspection`. Plan-backed and explicit ad hoc method
cases use the same execution path. If none exist, return to the router.

Do not infer Browser work from an item metadata flag and do not create
kind-specific requirements. The method contract is the authority.

## 2. Resolve the target URL and freshness identity

Use the registered item and ephemeral-environment reads:

```bash
_item_project=$(yoke items get {N} project)
_item_branch=$(yoke items get {N} worktree)
yoke ephemeral-env get "$_item_project" "$_item_branch" --json
```

Read the environment URL and deployed SHA. Read the worktree HEAD through
`git -C "{WORKTREE_PATH}" rev-parse HEAD`. If the deployment is absent or its
SHA is stale, run the project's normal deployment path and retry this gate.
Do not execute Browser cases against an unknown build.

## 3. Execute each case

```bash
yoke qa case run \
  --requirement-id <requirement-id> \
  --base-url "<environment-url>" \
  --expected-branch "<worktree-branch>" \
  --expected-sha "<worktree-head-sha>"
```

The shared runner starts the Browser substrate, executes only the named case,
records the run, stores screenshot/trace evidence, and returns its outcome.
Do not add another run manually.

- `pass`: continue.
- `fail` or executor error: block, fix the defect or environment, then rerun
  the same requirement.
- `inconclusive` / `needs_review`: leave the transition blocked and surface
  the generated QA review request in the Inbox. Approval marks the case passed;
  rejection marks it failed; waiver uses the ordinary requirement waiver.

## 4. Confirm the union gate

After all Browser cases are resolved, use the typed gate summary for the
transition. Continue only when the union of every blocking materialized and ad
hoc requirement passes or is waived.

Evidence review uses `yoke qa artifact read --requirement-id N --artifact-id N`.
That surface returns inline local evidence or a short-lived durable URL and
reports non-portable/on-machine evidence explicitly.
