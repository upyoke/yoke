# Advance — Browser QA Execution Gate

Called at a workflow transition that has attached Browser-method cases. The
same flow executes both built-in methods:

- `browser-check`: assertions produce an automatic verdict.
- `browser-inspection`: capture produces evidence for the plan's batched agent
  reviewer. Only an inconclusive agent verdict requests a human decision.

The gate is re-entrant. Materialization is idempotent and rerunning a case
records a new run.

## 1. Materialize and select Browser cases

```bash
yoke qa plan materialize \
  --item "PREFIX-{N}" \
  --transition "{_target}" \
  --json
yoke qa requirement list --item "PREFIX-{N}" --json
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
_item_branch=$(yoke item-worktrees get PREFIX-{N} \
  --lane-role implementation --field branch)
yoke ephemeral-env get "$_item_project" "$_item_branch" --json
```

Read the environment URL and deployed SHA. Read the worktree HEAD through
`git -C "{WORKTREE_PATH}" rev-parse HEAD`. If the deployment is absent or its
SHA is stale, run the project's normal deployment path and retry this gate.
Do not execute Browser cases against an unknown build.

## 3. Execute the ordered plan roster

```bash
yoke qa plan run \
  --item "PREFIX-{N}" \
  --transition "{_target}" \
  --base-url "<environment-url>" \
  --expected-branch "<worktree-branch>" \
  --expected-sha "<worktree-head-sha>"
```

The shared runner executes every case in immutable snapshot order, records
deterministic results, and stores Browser screenshot/trace evidence. Do not
add another run manually.

For a targeted recovery after the plan runner identifies one failed
requirement, use the same per-requirement execution contract:

```bash
yoke qa case run --requirement-id N
```

Normal transition execution remains plan-level; do not replace the ordered
plan run with a manually assembled series of case runs.

- Exit `0` / `pass`: continue.
- `fail` or runner error: block, fix the defect or environment, then rerun
  the same requirement.
- Exit `12` / `awaiting_agent_review`: immediately dispatch the returned typed
  `review_bundle.dispatch` through the harness subagent facility. Supply the
  complete immutable bundle and exact prompt to its `subagent_type`; the
  reviewer inspects every visual and transcript, then runs the returned
  `submit_command` with one verdict and rationale per case. This state is
  pending agent review, never evidence that a human request exists.
- A submitted `pass` continues and `fail` blocks. Only submitted
  `inconclusive` creates the human Inbox request; approval, rejection, and
  waiver then use the ordinary review-resolution paths.

## 4. Confirm the union gate

After all Browser cases are resolved, use the typed gate summary for the
transition. Continue only when the union of every blocking materialized and ad
hoc requirement passes or is waived.

Evidence review uses `yoke qa artifact read --requirement-id N --artifact-id N`.
That surface returns inline local evidence or a short-lived durable URL and
reports non-portable/on-machine evidence explicitly.
