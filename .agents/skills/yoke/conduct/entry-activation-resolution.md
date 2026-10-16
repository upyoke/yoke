# Conduct — sync, fan-out and lane activation

Input: full _epic_ref, PROJECT, MAIN_ROOT, the live pin and effective policies.
Keep parent ref separate from each local task number. Runtime task data lives
in the control plane; resolved lane code is that task's execution authority.

## Sync gate

```text
yoke workflow-item epic-dispatch-chain list --epic PREFIX-N --json
yoke epic-tasks list --epic PREFIX-N --json
yoke items github-sync PREFIX-N
```

Ready means the task graph and its local dispatch chains exist. GitHub task
issues are optional: disabled mirroring still generates local chains through
items.github_sync. If chains are absent, first require a task graph;
task_graph_missing routes the exact pin back to authoring. Auto-sync, then
re-read tasks and chains. Missing afterward halts with sync failure and the
same recovery command. The current holder runs this idempotent repair; another
live holder keeps ownership. Dependencies and lane activation still gate work.
Advance only the next declared stage inside Conduct's binding. A DB-only sync with no tracked changes succeeds;
commit actual tracked changes only, never BOARD. Legacy root DB files stop.

Resolve LIVE_STAGE and IMPLEMENTING_STAGE from the immutable pin and verify
the resulting stage; no remembered progression or scalar status shortcut:

```text
yoke lifecycle transition PREFIX-N --from {LIVE_STAGE} --to {IMPLEMENTING_STAGE} --reason "Conduct: synced graph ready for activation" --json
```

## Epic Fan-Out Enumeration

Read every chain/current task. Completed done/reviewed-implementation heads
advance; planned is a candidate; blocked reports its reason. For implementing/
reviewing-implementation, require that task's result.head_dispatch row from
the registered chain get/list, including task_num, decision, reason and
holder_session_id. No absent-field or local-import fallback:

| decision | Action |
|---|---|
| resumable | Candidate; retain its registered lane and prior notes/reviews. |
| busy | Report busy head; continue independent chains. |
| blocked | Report authenticated holder; no acquire or lane writes. |
| unknown / missing row or fields | Stop this candidate, report named read/identity/chain repair; reread. |

The read does not reclaim/advance; exact task acquire remains the final gate.
Never age-reclaim a protected live claim holder. Required producer unavailable
is a deployment/control-plane recovery, not permission to reconstruct a decision.

Per candidate, exclude only when another task on the same branch is implementing
or reviewing-implementation, or a dependency is not done/reviewed-implementation.
Check each Expects provider and its named files/exports. Independent chains
continue. Surviving local task numbers form _task_ids; retain each
_worktree_branch_${_task_id} and _worktree_path_${_task_id}. Primary aliases point
only at the first candidate. Empty list reports complete/busy/blocked/mixed
accurately; all tasks complete means fresh parent handoff, never parent done.

## Activate before dispatch

Activate planned path claims only when the effective claims axis requires them.
These are path-claim states, not item lifecycle statuses. Registered preparation
activates required claims and provisions every project-routed lane on Yoke's installed interpreter, before a lane exists:

```text
yoke worktree prepare --item "${_epic_ref}" --project "${PROJECT}"
```

Read `yoke worktree prepare --help` for entry and recovery. Preparation is
idempotent on correct existing branches. Upstream-unverified/stale,
dirty main, capacity or wrong lane stops with exact recovery; no reset/rebase,
borrowed project or guessed path. Complete this before each task baseline.

For every _task_id, hydrate only its suffixed branch/path. Read its task body
and registered lane; if chain path is empty, find the matching item_worktrees
row. Missing row stops for path-record/operator repair, never string assembly.

```text
yoke workflow-item epic-task body-get --epic PREFIX-N --task-num {task_num}
yoke item-worktrees list PREFIX-N --json
git -C "${MAIN_ROOT}" rev-parse "${_worktree_branch}"
```

Store TASK_BASELINE_${_task_id} once and retain it across retries. Before the
task claim, branch-ref reads through MAIN_ROOT avoid unauthorized lane access.
Read worktree_plan's Cross-Task Merge Plan; each predecessor must be reviewed
or done. Delegated claimed-lane merge always runs, including idempotent reentry:

```text
git -C {WORKTREE_PATH} merge {PREDECESSOR_BRANCH} --no-edit
```

Unfinished predecessor/conflict halts for pinned authoring repair. No plan means
skip that step. Do not mutate a lane before its exact task claim permits it.

```text
yoke conduct epic-task update-status --epic PREFIX-N --task-num {task_num} --status implementing --note "Dispatched by conduct (task fan-out)"
yoke workflow-item epic-task metadata-update --epic PREFIX-N --task-num {task_num} --fields-json '{"worktree":"BRANCH","branch":"BRANCH","worktree_path":"ABS_PATH"}'
yoke workflow-item epic-dispatch-chain refresh-activation --epic PREFIX-N --worktree {BRANCH} --task-num {task_num}
```

Pipeline update owns attempts/history/derive; the generic status writer is not
equivalent. Preserve all three resolved metadata fields and architect lanes.
Refresh current_task/current_attempt/last_updated. Re-read each task: require
implementing/reviewing-implementation before Engineer; planned stops for this
activation repair. Continue this session, no relaunch or parent stop.

Cold context carries parent ref/title/project, local task number and optional
GitHub issue, exact lane/branch/MAIN_ROOT, spec reads, registered progress/review
writes,
QA roster and dependencies. [dispatch-context.md](dispatch-context.md) owns
assembly. Run capability-based ephemeral preparation once per branch/dispatch
cycle through [dispatch-context-ephemeral.md](dispatch-context-ephemeral.md).

Next: [engineer-tester-loop.md](engineer-tester-loop.md).
