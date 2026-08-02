# Advance — Deployed-Stack QA

Called by the advance router when the workflow transition is `release`.
Materializes and executes the project's attached deployed-stack QA plan cases.
Skip for every other transition.

For `worktrees=worker_and_integration_lanes`, execute the release case on each
task lane through the pinned `conduct` executor; the parent item has no single
worktree and must not substitute the main checkout.

The deployed-stack case uses the shared `Command` method. Its project-owned
configuration declares the exact command and that `BASE_URL` is required. The
case runner resolves the item's worktree, captures the complete command output,
records the QA run and artifact, and returns the requirement verdict.

**Context variables** (set by router): `{N}`, `_item_project`

**This gate is re-entrant:** materialization is idempotent and another execution
of the same requirement records a new run.

---

## 1. Materialize attached cases

Use the registered plan materialization surface:

```bash
yoke qa plan materialize \
  --item "PREFIX-{N}" \
  --transition release \
  --json
```

Then read the item's typed requirements:

```bash
yoke qa requirement list --item "PREFIX-{N}" --json
```

Select unsatisfied, non-waived plan cases whose `method_id` is `command` and
whose `method_config.registered_scope` is `e2e`. If none exist, report that the
project has no deployed-stack plan attached at `release` and continue. This is
an advisory, not a blocker.

Do not recreate a free-form `e2e` requirement and do not read project-structure
settings. The attached plan case is the executable contract.

## 2. Resolve the deployment URL

Resolve the item project and branch through registered reads, then read the
ephemeral environment:

```bash
_item_project=$(yoke items get {N} project)
_item_branch=$(yoke item-worktrees get PREFIX-{N} \
  --lane-role implementation --field branch)
yoke ephemeral-env get "$_item_project" "$_item_branch" --json
```

Use the returned environment URL as `BASE_URL`. If the environment is absent,
pending, or has no URL, block without changing lifecycle state:

> **Blocked:** Deployed-stack QA requires the release candidate URL. Wait for
> the ephemeral deployment to publish it, then retry this transition.

## 3. Execute every deployed-stack case

Execute each selected requirement through the shared case runner:

```bash
yoke qa case run \
  --requirement-id <requirement-id> \
  --base-url "<environment-url>"
```

The runner records the command, verdict, and full captured output. Do not add a
second manual `qa.run` row.

- Exit `0` with verdict `pass`: continue after every selected case passes.
- Exit `1` with verdict `fail`: block the transition and report the returned run
  id and artifact id.
- Exit `2`: treat the executor contract as invalid, block, and report the exact
  error.

After every deployed-stack case passes, return to the router for finalization.
