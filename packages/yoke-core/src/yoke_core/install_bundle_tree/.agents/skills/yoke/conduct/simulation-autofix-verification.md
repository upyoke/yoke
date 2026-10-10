# Conduct — one code-gap amend cycle

Only after Simulate returns AUTOFIX_CODE_GAPS. Maximum one amend cycle; retain
parent/project, exact registered lane/branch, current report and max attempts.
Latest concrete CRITICAL/WARNING code gaps are cross-checked against accumulated
Architect classifications; no invented scope or duplicate completed work.

## Create and activate the fix task

Parse Tasks involved forms #N/#NNN/Task N/plain numbers. Deduplicate, sort and
zero-pad; exclude the eventual fix task itself. Unparseable source refs mean
empty task dependency set, not guessed ids. Resolve next local task number from
actual rows, never items.id. Task body contains description, each gap severity/
root cause/fix/files, behavioral ACs, test plan and actual file scope/budget.

```text
yoke workflow-item epic-task simulation-get --epic PREFIX-N --phase integration --json
yoke epic-tasks list --epic PREFIX-N --json
yoke workflow-item epic-task add --epic PREFIX-N --title "Fix integration simulation gaps" --worktree {BRANCH} --context-estimate M --dependencies {DEPENDENCIES} --body-file {TASK_FILE}
yoke workflow-item epic-task update-status --epic PREFIX-N --task-num {FIX_TASK} --status planned
yoke workflow-item epic-task history-insert --epic PREFIX-N --task-num {FIX_TASK} --from-status none --to-status planned --note "Created by conduct auto-fix"
yoke workflow-item epic-task file-add --epic PREFIX-N --task-num {FIX_TASK} --file-path {FILE} --action modify
yoke items github-sync PREFIX-N
```

Sync is idempotent; only new task gets issue. Verify exact lane/chain, append
fix task to its queue and refresh activation through registered chain writes.
No task graph mutation outside the parent's project or lost required claims.

```text
yoke workflow-item epic-dispatch-chain get --epic PREFIX-N --worktree {BRANCH} --json
yoke workflow-item epic-dispatch-chain update --epic PREFIX-N --worktree {BRANCH} --field queue --value '{UPDATED_QUEUE_JSON}'
yoke conduct epic-task update-status --epic PREFIX-N --task-num {FIX_TASK} --status implementing --note "Dispatched by conduct auto-fix" --claim-bypass "simulation-autofix:epic-PREFIX-N"
```

The documented system-owned transition bypass is not lane write authority.
Acquire/verify exact task claim before every Engineer/Tester and hold normal
scope coverage. Record fix task/attempt baselines and note watermark. Render the
shared Engineer descriptor and complete cold project/QA context; use task and
parent spec reads, exact ref and local task number, never PREFIX-{internal_id}.

After Engineer immediately capture reflections and run ALL normal submission
gates, including same-attempt max20turn submit-only repair. A rescue commit is
still a blocker. Record actual agent id and seed review only after passing.
Merge verified current target; delegate conflicts once, unresolved→AUTOFIX_HALTED.

## Tester and final simulation

Render [shared Tester](../shared/tester-dispatch-template.md) for this exact task,
with registered lane/QA/dependencies and size-gated baseline/task/retry diffs.
Capture artifacts/reflections and durable review. Text-only verdict requires its
attributed native insertion/readback. Genuine FAIL records failed and returns
AUTOFIX_HALTED: no implementation retry in this one amend cycle. No-verdict gets
the two minimal output retries; still absent→HALTED, no synthetic amend PASS.
PASS review-insert advances task; release only its exact task claim.

Refresh all task/status/lane authorities for final Simulator, not main code.
Every prompt is identity-attested, requiring SIMULATION: CLEAN/GAPS FOUND then
EPIC: {public_ref}, using the complete public ref, never an internal id. Preserve Worktree-State Authority and actual _worktree_list.
Use [simulation criteria](simulation-gate-criteria.md) and bounded output gate;
persist once through simulation-upsert --json and require verified=true,
matching identity/phase/verdict and positive requirement_id/run_id.

Final CLEAN returns AUTOFIX_CLEAN for actual parent gates/lifecycle handoff;
remaining GAPS returns AUTOFIX_HALTED with report. Wrong-epic body/missing-epic
body/readback refusal returns exact diagnostic without treating the identity
failure as an ordinary gap. No repeat uncertain write, synthetic CLEAN, second
amend cycle or source helper fallback. Restore caller mode and preserve lanes.
