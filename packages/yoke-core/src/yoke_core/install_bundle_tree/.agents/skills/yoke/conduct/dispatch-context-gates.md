# Conduct — task gates

Sync and same-worktree candidate filters reuse
[entry-activation-resolution.md](entry-activation-resolution.md). Require
dependencies done/reviewed and Expects providers' named files/exports; exclude
only affected candidate, not independent chains.

## First-dispatch plan gap gate

Only when no task progressed beyond planning/planned, read plan simulation:

```text
yoke workflow-item epic-task simulation-get --epic PREFIX-N --phase plan --json
```

An explicitly absent legacy plan report passes this read-only initial gate;
other read failures halt. This does not permit missing required head_dispatch
or verified integration receipt fallback. Count case-sensitive [CRITICAL] in
the actual body. Unresolved criticals halt unless explicit --force/--ignore-gaps;
print every gap and exact override warning before proceeding. WARNING/NOTE
alone passes. No fabricated simulation write or waived blocking requirement.

## Post-Engineer submission gate

After each return immediately capture reflections, then read a durable receipt
newer than the attempt's progress-note watermark:

```text
yoke workflow-item epic-task submission-receipt-get --epic PREFIX-N --task-num {task_num} --after-note-count {NOTE_COUNT}
```

Require ---SUBMISSION-CHECKS-START--- / ---SUBMISSION-CHECKS-END--- in the new
epic_progress_notes row; tool-result summary is insufficient, on every harness.
Required keys: test_plan, files_touched, edited_tests, clean_worktree,
progress_notes, file_budget. First three permit PASS or explicit SKIP;
clean_worktree requires PASS. A new commit requires progress_notes: PASS and
increased note count; SKIP only without commit. Authored code created/grown
requires file_budget: PASS attesting every authored file≤350 even with policy
off; SKIP only when no authored code grew. Missing/malformed/FAIL/UNKNOWN fails.

Also inspect branch HEAD, last commit and dirt. A safety-net auto-commit is not
valid submission. Unexpected dirty state may be preserved by an own-lane rescue
commit with exact affected files, Ouroboros record and synthetic progress note;
the rescue remains a blocker, never automatic review readiness. No generated
board/legacy DB staged; preserve others' work.

## Same-attempt submit-only remediation contract

Every missing receipt/key/note, failed line, dirty safety-net or rescue case
re-dispatches Engineer at SAME attempt; do not increment attempt or seed review.
Prompt names the exact deficiency and existing branch deliverable:

> This is a bounded submission-only remediation (max 20 turns). Do NOT start new work.

Allowed: finish remaining commit, append missing required progress note and its
receipt, then stop. Forbidden: new implementation/exploration/tests/refactors.
Re-run the gate after return. Do not convert submission remediation into a
full implementation retry or advance from a safety-net commit.

After every gate passes, record actual Engineer agent id and seed exact review:

```text
yoke workflow-item epic-task metadata-update --epic PREFIX-N --task-num {task_num} --fields-json '{"agent_id":"ENGINEER_AGENT_ID"}'
yoke workflow-item epic-task review-seed --epic PREFIX-N --task-num {task_num}
```

Seed is idempotent and advances task to reviewing-implementation. It does not
complete the parent. Continue with claimed-lane merge and shared Tester prompt.
