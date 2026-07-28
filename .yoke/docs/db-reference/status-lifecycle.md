# DB Reference — Status Lifecycle

Item-level and epic-task-level status lifecycles, with valid transitions, derivation rules, and gate enforcement points. Cross-link back from [db-reference.md](../db-reference.md) for entry points, the domain catalog, and the per-table reference.

## Item Workflow Lifecycle (`items` table)

Every item pins `workflow_id` and `workflow_version_id`. The immutable
definition owns its ordered stages, terminal stages, gates, policies, and
registered executor bindings. Read the authoritative definitions with
`yoke workflows definition get`; do not reconstruct stage tables from this
reference.

The runtime additionally recognizes the engine-owned exceptional stages
`cancelled`, `stopped`, `failed`, and `blocked`. Item-level `blocked` is
retained only as compatibility vocabulary; normal blocking uses the orthogonal
flag described below.

> Item-level `blocked` is not a lifecycle status. Use the orthogonal `items.blocked` flag (set via `/yoke block YOK-N "<reason>"`, cleared via `/yoke unblock YOK-N`) — the flag preserves the lifecycle status. Epic-task `status='blocked'` semantics use the lifecycle status. Full architectural-why (yoke source repo): `docs/archive/decisions/blocked-flag-retirement.md`.

The item-level lifecycle is therefore a definition shape, not a global status
table:

| Definition field | Runtime meaning |
|---|---|
| `stages` | Ordered ids, display labels, descriptions, and target-stage gate references |
| `terminal_stage_ids` | Successful terminal stages for this version |
| `transitions` | Declared graph edges between stages |
| `executor_bindings` | Registered executors covering contiguous half-open stage intervals |
| `policies` | Ownership, worktree, task-child, QA, approval, and delivery behavior |
| `entry_surfaces` | Create surfaces permitted to pin this workflow version |

`yoke workflows definition get` serves current selections and the gate
catalog. `yoke workflows item get YOK-N` plus
`yoke workflows version get WORKFLOW VERSION` serves the exact authority for
an existing item. Board buckets are a projection over item stage and workflow
context; they do not define valid transitions.

**Transition enforcement:** `yoke lifecycle transition` loads the item's pinned
definition, validates target-stage membership, evaluates the gate references
attached to that target, and dispatches policy behavior through the canonical
status-write path. Ordered stages and declared edges drive navigation and
forward-transition checks. Executor ownership comes from the binding whose
interval contains the live stage, not from the workflow id or a copied status
table.

`shepherd_verdicts` records artifacts produced while a definition-bound
`shepherd` segment runs. Those records do not create lifecycle authority:
the pinned version still owns the segment endpoints and all target-stage gate
references.

## Epic Task Status Lifecycle (epic_tasks table)

`epic_tasks` rows are persisted children of an item whose pinned workflow
declares `policies.generated_children=epic_tasks`. Their lifecycle vocabulary
is independently canonical and remains valid regardless of the parent
workflow's registry id:

### Lifecycle Diagram

```
planning -> plan-drafted -> refining-plan -> planned -> implementing -> reviewing-implementation ->
 reviewed-implementation -> polishing-implementation -> implemented -> release -> done
 Plus: failed, blocked, stopped
```

### Status Reference

| Status | Meaning | Terminal? |
|---|---|---|
| `planning` | Task is being designed | No |
| `plan-drafted` | Task plan written, awaiting review | No |
| `refining-plan` | Task plan under refinement | No |
| `planned` | Task is queued for dispatch | No |
| `implementing` | Task is being worked on by an agent | No |
| `reviewing-implementation` | Task is being tested/reviewed | No |
| `reviewed-implementation` | Testing/review passed, awaiting polish | Yes (success) |
| `polishing-implementation` | Final polish pass | Yes (success) |
| `implemented` | Implementation complete, awaiting release | Yes (success) |
| `release` | In deployment pipeline | Yes (success) |
| `done` | All work complete | Yes (success) |
| `failed` | All dispatch attempts exhausted | Yes (failure) |
| `blocked` | Waiting on dependency | No |
| `stopped` | Agent session ended unexpectedly | No |

Terminal success (TASK_TERMINAL_SUCCESS): `{reviewed-implementation, polishing-implementation, implemented, release, done}`.

### Valid Transitions

| From | To | Trigger |
|------|----|---------|
| `planning` | `plan-drafted` | Task plan is written during shepherd planning. |
| `plan-drafted` | `refining-plan` | Task plan enters refinement. |
| `refining-plan` | `planned` | Task plan refinement complete; task is queued. |
| `planned` | `implementing` | Conduct dispatches the task to an engineer agent. |
| `planned` | `blocked` | Dependencies are not yet met at dispatch time. |
| `implementing` | `reviewing-implementation` | Engineer finishes work; task enters testing. |
| `implementing` | `failed` | Engineer exhausts max retry attempts. |
| `implementing` | `blocked` | External dependency discovered during work. |
| `implementing` | `stopped` | Manual halt by operator. |
| `reviewing-implementation` | `reviewed-implementation` | Tester review passes. |
| `reviewing-implementation` | `implementing` | Tester review fails; task returns for rework. |
| `reviewed-implementation` | `done` | Branch merged and post-merge cleanup complete. |
| `blocked` | `planned` | Auto-unblock: all dependency tasks reach terminal success. Conduct's S6c enumeration picks the task up and authors the canonical `planned → implementing` transition on dispatch. |
| `failed` | `planned` | Manual retry (reset by operator). |
| `stopped` | `planned` | Manual restart (re-queued by operator). |

### Bypass Closure

`yoke workflow-item epic-task metadata-update` delegates to `yoke workflow-item epic-task update-status` when the field is `status`. This ensures enum validation and QA gate checks always apply, regardless of which code path writes the status.

### Enforcement

`yoke workflow-item epic-task update-status` validates against the 14-value canonical set (`planning|plan-drafted|refining-plan|planned|implementing|reviewing-implementation|reviewed-implementation|polishing-implementation|implemented|release|done|failed|blocked|stopped`) and rejects invalid values with a clear error message.

`yoke_core.domain.update_status` follows the same canonical-only contract. Non-canonical inputs fail immediately instead of being normalized.

### Auto-Derivation of Parent Item Status

When a task status changes, `yoke_core.domain.update_status` automatically
recomputes the task-graph parent item's status from aggregate task states:

| Condition | Derived Parent Status |
|---|---|
| All tasks `planning` or `planned` (or + `blocked`) | `planned` |
| Any task `implementing` or `reviewing-implementation` | `implementing` |
| All tasks in TASK_TERMINAL_SUCCESS | `reviewing-implementation` |
| Mixed terminal: some `failed`/`stopped` + some success | `implementing` (operator intervention needed) |

**Guard:** Auto-derivation only fires when the parent item's current status is
`planned`, `implementing`, `reviewing-implementation`, or
`reviewed-implementation`. If the parent has advanced beyond that range, the
task updater does not derive it backward.

### Board Progress

`yoke board rebuild` computes generated-task progress as terminal-success
tasks (TASK_TERMINAL_SUCCESS: `reviewed-implementation`,
`polishing-implementation`, `implemented`, `release`, or `done`) out of total
tasks. These statuses count toward the progress percentage displayed on the
parent item.

### Merge Pre-Flight

The merge pre-flight check PF-3 (owned by `yoke_core.engines.merge_worktree_prepare`) queries for tasks with `status NOT IN ($(_sql_task_terminal_success_list))` — currently `'done','implemented','polishing-implementation','release','reviewed-implementation'`. Any such tasks block the merge.

### Auto-Unblock

When a task transitions to a terminal-success state,
`yoke_core.domain.update_status` checks all `blocked` siblings. If every
dependency has reached terminal success, the task returns to `planned`;
Conduct later authors the separate `planned -> implementing` transition when
it dispatches that task.

### Dispatch

The current `conduct` executor dispatches generated tasks in `planned` status.
Parent-item routing to Conduct still depends on the parent's pinned
`executor_bindings` and task-graph policies.
