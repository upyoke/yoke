# Conduct — single-task dispatch

Initialize attempt=1 and output-failure counter=0 once per task. Read baselines
through the owning main checkout's branch ref before task claim:

```text
git -C {MAIN_ROOT} rev-parse {BRANCH}
git -C {MAIN_ROOT} merge-base {BRANCH} main
```

Only a first task whose preserved TASK_BASELINE equals merge-base and differs
from current branch HEAD may skip Engineer on attempt1. Later chain tasks
always dispatch Engineer; every retry does too. Record ATTEMPT_BASELINE and
progress-note count before each attempt. Never overwrite the task baseline.
Skipped implementation still seeds review, merges current target and gets Tester.

## Exact task custody before Engineer and Tester

```text
yoke claims work acquire --epic PREFIX-N --task-num {task_num} --reason "engineer dispatch"
yoke sessions identity --json
yoke db read --format lines "SELECT 1 FROM work_claims WHERE session_id='{SESSION_ID}' AND target_kind='epic_task' AND scope::jsonb->>'epic_id'=(SELECT item_id::text FROM item_refs WHERE public_ref='PREFIX-N') AND scope::jsonb->>'task_num'='{task_num}' AND released_at IS NULL"
```

Require this active same-session row; absent/refused reads HALT: engineer
dispatch. The parent coordination claim cannot replace task custody. Same-session
reacquire is idempotent; claim_conflict skips the affected task without writing
its lane. Reacquire and verify before Tester as well:

```text
yoke claims work acquire --epic PREFIX-N --task-num {task_num} --reason "tester dispatch"
```

Missing active same-row proof HALT: tester dispatch; recover through acquire,
then reread. Never construct a worktree DB path or guess session identity.

Rehydrate through [dispatch-context-rehydrate.md](dispatch-context-rehydrate.md).
Render the Engineer descriptor with the complete cold prompt from
[dispatch-context-prompts.md](dispatch-context-prompts.md); use the registered
lane, no isolation. Exact task spec and parent spec, retry feedback, QA commands,
effective File Budget/path-claim axes, naming/350/simplify and durable submission rules travel
with it. Continue immediately on return.

Run [dispatch-context-gates.md](dispatch-context-gates.md)'s receipt, dirty-exit,
progress-note and rescue gates. Failure re-dispatches submit-only remediation
for the SAME attempt; no Tester/advance until clean. Capture reflections and
review artifacts through [dispatch-context-artifacts.md](dispatch-context-artifacts.md).
Seed review after submission succeeds:

```text
yoke workflow-item epic-task review-seed --epic PREFIX-N --task-num {task_num}
```

Merge verified current integration target into this claimed lane, capture exit
and delegate conflicts to its Engineer. Unresolved conflict halts this task.
Never reset/rebase or silently substitute stale local target:

```text
git -C {WORKTREE_PATH} merge {INTEGRATION_TARGET} --no-edit
```

Prepare full/task/attempt diffs under the sole size-gate owner in
[dispatch-context-prompts.md](dispatch-context-prompts.md), never manual ellipsis.
Render [the shared Tester template](../shared/tester-dispatch-template.md), with
task identity, QA/project context, dependency interfaces, downstream bodies,
claim coverage and exact capture paths. Continue immediately after Tester at
[engineer-tester-closeout.md](engineer-tester-closeout.md).
