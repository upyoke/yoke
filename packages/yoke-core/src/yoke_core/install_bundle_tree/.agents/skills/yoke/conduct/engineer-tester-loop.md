# Conduct — Engineer/Tester loop

Input _task_ids contains local task numbers; _epic_ref is always the parent.
One member uses [engineer-tester-dispatch.md](engineer-tester-dispatch.md), then
[engineer-tester-closeout.md](engineer-tester-closeout.md). For _batch_size > 1,
use [dispatch-context-dispatch.md](dispatch-context-dispatch.md) and
[dispatch-context-prompts.md](dispatch-context-prompts.md): all Engineers in one
batch, gate each return, then all eligible Testers in one batch.

Hydrate each task's _worktree_branch_${_task_id}, _worktree_path_${_task_id},
TASK_BASELINE_${_task_id}, ATTEMPT_BASELINE_${_task_id}, _attempt_${_task_id},
_tester_output_failures_${_task_id} and feedback before its closeout; write
updates back to that task's state. Never reuse another task's lane or counters.
Task baseline survives retries; attempt baseline refreshes each attempt.

Apply closeout per task. PASS advances its chain independently; FAIL retries
only that task. Unparseable/exhausted output halts the affected task, preserving
reviewed siblings. Fresh entry enumerates registered head_dispatch again,
including prior notes/reviews; no absent-field or source-import fallback.
The parent reaches integration only after every chain is reviewed/done.

## Per-task work-claim re-entry semantics

| Case | Action |
|---|---|
| Same-session re-acquire | Idempotent already_owned=true; verify active exact task claim before dispatch. |
| Other-session-held | claim_conflict names holder; classify with head_dispatch, skip affected task, no lane write. |
| Stale-by-absent-session | Only authoritative acquire/reclaim may decide prior custody ended; retain its receipt. Protected live ownership is not reclaimed by age. |

The parent item claim coordinates the epic; each epic_task claim authorizes its
registered lane. Reads are diagnostic; exact acquire is the final dispatch gate.
Each Tester closeout releases only its task claim, and retry reacquires it.

No-chain or exhausted attempt goes to [cleanup-report.md](cleanup-report.md).
All tasks reviewed/done goes to [simulation-gate.md](simulation-gate.md).
