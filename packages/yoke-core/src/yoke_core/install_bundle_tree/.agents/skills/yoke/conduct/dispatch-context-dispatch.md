# Conduct — parallel dispatch and per-task advance

## Harness concurrency

Read `parallel_subagents` in `.yoke/harness/<harness-dir>/manifest.json`
(claude-code → claude) before the first dispatch; never assume concurrency
the manifest does not state. `supported` dispatches every eligible Engineer
at once through the named mechanism and handles each return as it arrives.
Any other value dispatches one sub-agent at a time in _task_ids order and
records the serial deferral once per Conduct leg:

```text
yoke items progress-log append PREFIX-N --headline "serial dispatch: parallel_subagents=<value> on <harness>" --stdin
```

## Engineer Dispatch

Generated task policies and registered lane rows own the dispatch. Before each
command hydrate _worktree_branch_${_task_id}/_worktree_path_${_task_id}; parent
_epic_ref stays unchanged. Record task baseline once; record attempt baseline
and prior note count every attempt through main's branch ref before task claim.
The first-task/merge-base skip rule and exact Engineer/Tester custody are in
[engineer-tester-dispatch.md](engineer-tester-dispatch.md); apply them per task.

Rehydrate and render [dispatch-context-prompts.md](dispatch-context-prompts.md)
for every task. Dispatch every eligible Engineer together; no isolation.
When effective path claims are enabled, read actual active coverage:

```text
yoke claims path list --item PREFIX-N --state active --json
```

Inline ## Active Path Claim Coverage. Planned (Widen Before Write) lists required
uncovered paths from enabled File Budget, otherwise task scope/survey. Claim
off omits claim blocks; budget can still govern sizing. Neither narrows scope.
Tester receives the same coverage read-only; uncovered fix routes to parent
for widening/reconciliation. Persisted anticipated paths are read-only context.

## Per-task pipeline as each Engineer returns

Never wait for sibling Engineers. The moment one Engineer returns, run that
task's whole pipeline while the others keep running: reflection and its
[submission gates](dispatch-context-gates.md), main merge, Tester, closeout
and lane advance below. Retain only summary/commit count in active context;
durable receipt and actual lane hold the deliverable. A failure gets
same-attempt submit-only remediation for that task only.

Merge verified current target into that task's claimed lane:

```text
git -C {WORKTREE_PATH} merge {INTEGRATION_TARGET} --no-edit
```

Capture exit; report conflict files and re-dispatch only that Engineer. An
unresolved task stays out of Tester eligibility; other tasks proceed.
No reset/rebase. Prepare the task's own diffs/context, render the Tester
template through [dispatch-context-prompts.md](dispatch-context-prompts.md)
and dispatch its Tester at once. No-verdict counter is separate from genuine
FAIL and uses [retry-budgets.md](retry-budgets.md).

## Post-PASS lane advance and refill

Durable review-insert advances only that task; never manually close the parent,
GitHub issue or remove lane. Conduct's integration gate waits for all tasks.

Unless no-chain, advance the completed task's chain through registered surface:

```text
yoke workflow-item epic-dispatch-chain advance --epic PREFIX-N --worktree {BRANCH}
yoke workflow-item epic-task get --epic PREFIX-N --task-num {NEXT_TASK}
```

Advance returns new_index|next_task_num: the lane's first queued planned task
whose dependencies are complete. chain_waiting names each remaining task and
what it waits on; the lane idles until a dependency completes. chain_complete
ends the lane. Any other refusal is its named recovery. A completed task can
unblock other lanes, so after each PASS also advance every idle chain and
dispatch every returned task now. Waiting tasks remain required and visible.

Before a next dispatch clear previous body/context/feedback, reset only that
task's attempt/output counters, reload authoritative spec/project/QA and run
activation again. Never skip status+metadata+chain refresh after advance.
No-chain reports next task and exits this leg. When every chain returns
chain_complete, simulation entry follows. Chains still waiting with no task
running anywhere cannot progress: report each wait and halt for pinned
authoring repair. Bound delivery skill later owns PR, merge, issue closeout and
lane cleanup.
