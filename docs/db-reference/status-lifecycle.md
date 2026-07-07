# DB Reference — Status Lifecycle

Item-level and epic-task-level status lifecycles, with valid transitions, derivation rules, and gate enforcement points. Cross-link back from [db-reference.md](../db-reference.md) for entry points, the domain catalog, and the per-table reference.

## Item Status Lifecycle (items table)

Two progressions exist, selected by item type:

**Issue-workflow-type progression:**
```
idea → refining-idea → refined-idea → implementing → reviewing-implementation → reviewed-implementation → polishing-implementation → implemented → release → done
```

**Epic progression:**
```
idea → refining-idea → refined-idea → planning → plan-drafted → refining-plan → planned → implementing → reviewing-implementation → reviewed-implementation → polishing-implementation → implemented → release → done
```

An item can also be set to `cancelled`, `stopped`, or `failed` at any point.

> Item-level `blocked` is not a lifecycle status. Use the orthogonal `items.blocked` flag (set via `/yoke block YOK-N "<reason>"`, cleared via `/yoke unblock YOK-N`) — the flag preserves the lifecycle status. Epic-task `status='blocked'` semantics use the lifecycle status. Full architectural-why: [`docs/archive/decisions/blocked-flag-retirement.md`](../archive/decisions/blocked-flag-retirement.md).

| Status | Description | Board Placement |
|--------|-------------|-----------------|
| `idea` | Raw idea, not yet specified. | Backlog section |
| `refining-idea` | Idea is being refined into a specification. | Pipeline section |
| `refined-idea` | Specification complete, ready for design/planning. | Pipeline section |
| `planning` | (Epic only) Being decomposed into tasks. | Pipeline section |
| `refining-plan` | (Epic only) Plan is being refined. | Pipeline section |
| `planned` | (Epic only) Broken into tasks, estimated. | Pipeline section |
| `implementing` | Currently being worked on. | Active section |
| `reviewing-implementation` | Meaningful implementation review and follow-up fixes are in progress. | Active section |
| `reviewed-implementation` | Implementation review passed; waiting for finishing review. | Active section |
| `polishing-implementation` | Finishing review is in progress. | Active section |
| `implemented` | Implementation and finishing review are complete; awaiting deployment. | Active section |
| `release` | Enrolled in a deployment run that is executing. | Active section |
| `done` | Deployment run succeeded and all blocking QA satisfied (or no deployment flow). | Done section |
| `cancelled` | Abandoned. Not shown on board by default. | Not displayed |

**Transition enforcement:** `yoke lifecycle transition` validates that the status value is one of the canonical set before routing the state change. The schema init CLI schema includes a CHECK constraint on the `items.status` column. The `yoke_core.engines.done_transition` script handles the tail of the lifecycle with automated side effects (GitHub label swaps, issue closure, board rebuild).

**Shepherd gates:** Certain transitions require Shepherd approval before advancing: `refined_idea_to_planning` (epics) and `planning_to_plan_drafted`. The Shepherd records verdicts in the `shepherd_verdicts` table. The `idea` to `refined-idea` transition is handled by `/yoke refine`, not shepherd.

## Epic Task Status Lifecycle (epic_tasks table)

Epic tasks use the implementation-family vocabulary aligned with the epic-workflow-type lifecycle. The canonical status values are:

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

### Auto-Derivation of Parent Epic Status

When a task status changes, `yoke_core.domain.update_status` automatically recomputes the parent epic's item status from the aggregate task states:

| Condition | Derived Parent Status |
|---|---|
| All tasks `planning` or `planned` (or + `blocked`) | `planned` |
| Any task `implementing` or `reviewing-implementation` | `implementing` |
| All tasks in TASK_TERMINAL_SUCCESS | `reviewing-implementation` |
| Mixed terminal: some `failed`/`stopped` + some success | `implementing` (operator intervention needed) |

**Guard:** Auto-derivation only fires when the parent epic's current status is `planned`, `implementing`, `reviewing-implementation`, or `reviewed-implementation`. If the parent has been manually advanced beyond `reviewed-implementation` (e.g., to `release` or `done`), auto-derivation does not override it. This prevents completed epics from regressing.

### Board Progress

`yoke board rebuild` computes epic progress as terminal-success tasks (TASK_TERMINAL_SUCCESS: `reviewed-implementation`, `polishing-implementation`, `implemented`, `release`, or `done`) out of total tasks. These statuses count toward the progress percentage displayed on the board.

### Merge Pre-Flight

The merge pre-flight check PF-3 (owned by `yoke_core.engines.merge_worktree_prepare`) queries for tasks with `status NOT IN ($(_sql_task_terminal_success_list))` — currently `'done','implemented','polishing-implementation','release','reviewed-implementation'`. Any such tasks block the merge.

### Auto-Unblock

When a task transitions to a terminal-success state, `yoke_core.domain.update_status` checks all `blocked` tasks in the same epic. If all of a blocked task's dependencies have reached terminal success, the blocked task is automatically transitioned to `implementing`.

### Dispatch

The conduct skill dispatches tasks in `planned` status. Tasks in any other status are skipped during dispatch.
