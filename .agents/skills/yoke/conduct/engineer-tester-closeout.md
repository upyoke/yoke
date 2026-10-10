# Conduct — Tester closeout

Immediately continue on each return. Capture reflections, inspect/commit actual
review artifacts through [dispatch-context-artifacts.md](dispatch-context-artifacts.md),
then stop the per-dispatch ephemeral environment on PASS or FAIL:

```text
yoke ephemeral-env update {env_id} status stopped
```

Only when env_id exists. Remove only this dispatch's known diff temp files after
analysis. Release the exact task claim on both verdict paths; retry reacquires:

```text
yoke claims work release --epic PREFIX-N --task-num {task_num} --reason "tester return"
yoke claims work holder-list --session-id-filter {SESSION_ID} --json
```

Release never touches the parent claim. A failure stays visible; inspect and
match target_kind=epic_task, epic_id and task_num. No parent-release fallback.

## Durable verdict, then output gate

```text
yoke workflow-item epic-task review-get --epic PREFIX-N --task-num {task_num}
```

Use the persisted review first. If absent but text has an unambiguous VERDICT:
PASS/FAIL, write its complete per-AC evidence to a local body file and insert
with Conduct attribution. A clear text verdict does not enter no-verdict retries:

```text
yoke workflow-item epic-task review-insert --epic PREFIX-N --task-num {task_num} --verdict PASS --body-file {REVIEW_FILE}
```

Use the actual verdict, not the example's PASS. Require durable row/readback.
No DB row and no clear verdict enters [retry-budgets.md](retry-budgets.md):
minimal/default, minimal descriptor escalation, then direct verification only
after output retries exhaust. Reflections/artifacts/readback run after each
return. A legitimate FAIL is a test result, not output failure.

## Process the verified result

PASS review-insert already advances the task to reviewed-implementation.
Report ref/task title, actual status, attempt/budget, branch/lane, commit range
and GitHub issue. Do not write parent terminal state. Unless no-chain, run the
independent chain advance in [dispatch-context-dispatch.md](dispatch-context-dispatch.md),
reset task counters, clear prior context/feedback and reactivate the next task.
Blocked successors stay visible; independent chains continue. All tasks reviewed/
done goes to [simulation-gate.md](simulation-gate.md). No-chain prints remaining
task and goes to cleanup with SUCCESS for this leg, not parent completion.

FAIL below the configured attempt limit retains feedback, increments attempt,
then uses pipeline status/chain counter writes and refreshes attempt baseline:

```text
yoke conduct epic-task update-status --epic PREFIX-N --task-num {task_num} --status implementing --note "Retry attempt {attempt} of {max_attempts}"
yoke workflow-item epic-dispatch-chain update --epic PREFIX-N --worktree {BRANCH} --field current_attempt --value {attempt}
```

Return to [engineer-tester-dispatch.md](engineer-tester-dispatch.md). Exhaustion
records failed, reports the task/attempts/lane/issue and actual recovery:

```text
yoke conduct epic-task update-status --epic PREFIX-N --task-num {task_num} --status failed --note "Exhausted attempts"
```

Then [cleanup-report.md](cleanup-report.md) with HALTED; preserve work.
