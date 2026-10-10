# Conduct — parallel dispatch and chain advance

## Parallel Engineer Dispatch

Generated task policies and registered lane rows own the batch. Before each
command hydrate _worktree_branch_${_task_id}/_worktree_path_${_task_id}; parent
_epic_ref stays unchanged. Record task baseline once; record attempt baseline
and prior note count every attempt through main's branch ref before task claim.
The first-task/merge-base skip rule and exact Engineer/Tester custody are in
[engineer-tester-dispatch.md](engineer-tester-dispatch.md); apply them per member.

Rehydrate and render [dispatch-context-prompts.md](dispatch-context-prompts.md)
for every task. All eligible Engineers dispatch in one batch; no isolation.
When effective path claims are enabled, read actual active coverage:

```text
yoke claims path list --item PREFIX-N --state active --json
```

Inline ## Active Path Claim Coverage. Planned (Widen Before Write) lists required
uncovered paths from enabled File Budget, otherwise task scope/survey. Claim
off omits claim blocks; budget can still govern sizing. Neither narrows scope.
Tester receives the same coverage read-only; uncovered fix routes to parent
for widening/reconciliation. Persisted anticipated paths are read-only context.

After ALL Engineers return, immediately run reflections and each task's
[submission gates](dispatch-context-gates.md). Retain only summary/commit count
in active context; durable receipt and actual lane hold the deliverable. Any
failure gets same-attempt submit-only remediation, not batch-wide pause.

## Main merge, then Parallel Tester Dispatch

Sequentially merge verified current target into each claimed task lane:

```text
git -C {WORKTREE_PATH} merge {INTEGRATION_TARGET} --no-edit
```

Capture exit; report conflict files and re-dispatch only that Engineer. An
unresolved task is removed from Tester eligibility; independent tasks proceed.
No reset/rebase. Prepare each task's own diffs/context and render the shared
Tester template through [dispatch-context-prompts.md](dispatch-context-prompts.md).
All eligible Testers dispatch in one batch; closeout is per task. No-verdict
counter is separate from genuine FAIL and uses [retry-budgets.md](retry-budgets.md).

## Post-PASS and task-lane auto-chain

Durable review-insert advances only that task; never manually close the parent,
GitHub issue or remove lane. Conduct's integration gate waits for all tasks.

Unless no-chain, advance the completed task's chain through registered surface:

```text
yoke workflow-item epic-dispatch-chain advance --epic PREFIX-N --worktree {BRANCH}
yoke workflow-item epic-task get --epic PREFIX-N --task-num {NEXT_TASK}
```

Advance returns new_index|next_task_num; exit1 means end-of-queue, other failure
is named recovery. Check next task dependencies. Unmet sets blocked with actual
refs/reasons and continues searching this chain; met/no dependencies dispatches.
Blocked tasks remain required and visible, not dropped from scope.

Before a next dispatch clear previous body/context/feedback, reset only that
task's attempt/output counters, reload authoritative spec/project/QA and run
activation again. Never skip status+metadata+chain refresh after advance.
No-chain reports next task and exits this leg. End-of-queue reports unresolved
blocked/planned tasks; only all chains reviewed/done enters simulation. Bound
delivery skill later owns PR, merge, issue closeout and lane cleanup.
