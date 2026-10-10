# Conduct — cold Engineer prompt and Tester diffs

## Engineer prompt

Dispatch ALL Engineers in parallel when the batch permits; one descriptor per
local task, parent identity unchanged. Render DispatchDescriptor(role="engineer")
through the harness descriptor owner; no isolation or independently chosen model.

```text
Implement PREFIX-{N} task {_task_id}: {task title}
Parent: {_epic_ref}; project: {PROJECT}; GitHub issue: {github_issue}
Registered lane: {WORKTREE_PATH}; branch: {BRANCH}; main owner: {MAIN_ROOT}
yoke workflow-item epic-task body-get --epic {_epic_ref} --task-num {_task_id}
yoke items get PREFIX-{N} spec
```

Include context from dispatch-context.md: exact project docs, materialized QA
roster and quick/full/E2E/smoke commands, Browser URL/branch/SHA, task baseline,
dependency interfaces/downstream bodies, current coverage and prior attempts.
Retries include exact feedback and attempt/budget. First work uses this lane;
commit incrementally and verify through registered project commands, not guesses.

Anticipated path coverage (pre-authorized) fills _anticipated_paths_block_{_task_id}
only from persisted ## Anticipated Paths in task body. Absent block omits heading;
do not recompute/mutate it. Uncovered required edits still widen before writing;
cross-task/new-surface scope routes pinned authoring repair. Enabled budget
requires its item/task section; disabled does not. Universal authored limit350,
target≤300, remains every posture. Apply reuse/quality/efficiency/future concepts
at author time; new infrastructure needs extension-versus-create justification.

Codebase-reader names/comments describe current function/mechanics/domain,
never item/plan/phase/task/AC/branch/batch provenance except runtime concepts.
Schema work follows the declared governed migration protocol before DDL.
Live/shared-state ACs default READ-ONLY; only explicit APPLY-MUTATION authorizes
sanctioned writes. Ambiguity reports evidence rather than repairing live state.
Do not create work items yourself.

Before returning, append final durable progress note with the agent definition's
---SUBMISSION-CHECKS-START--- / ---SUBMISSION-CHECKS-END--- and all six required
keys; source gate owns their PASS/SKIP semantics. Return short commit/test summary,
not repeated specs. Capture ---REFLECTION-START--- through the declared owner.

## Tester diff preparation

One size-gate definition, reused for task, full standalone and retry diffs:

```text
TESTER_DIFF_INLINE_MAX_LINES=300
git -C {WORKTREE_PATH} diff {TASK_BASELINE}..HEAD
git -C {WORKTREE_PATH} diff main...HEAD
git -C {WORKTREE_PATH} diff {ATTEMPT_BASELINE}..HEAD
```

Capture the full branch diff to a temp file always for generated tasks. Task
diff is task-baseline..HEAD; retry also supplies attempt-baseline..HEAD. Standalone
full diff is its task diff. At or below threshold inline the COMPLETE relevant
diff; above supply --stat and exact temp path. Do not manually truncate or
summarize with ellipsis, keep broad diffs in shell variables, or omit retry scope.
Build prompt/capture in one bounded step with each task's own lane/baselines.

Render [the shared Tester template](../shared/tester-dispatch-template.md) only:
exact task identity, parent/task specs, lane, QA/project commands, interfaces,
downstream bodies, same read-only coverage, full/task/retry diff slots and durable
review-insert. No local Tester prompt or substituted task-derived public ref.
Dispatch eligible Testers in parallel, continue immediately on each return,
capture reflections/artifacts and persist verdict. Retain feedback only for FAIL;
cleanup only this dispatch's known captures after analysis.

Minimal no-verdict retries use
[dispatch-context-prompts-minimal.md](dispatch-context-prompts-minimal.md).
