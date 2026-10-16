# Engineering implementation and submission

Read after verifying the lane, before implementation or verification, and
again before submission. These procedures apply to every engineering attempt.

## Implementation process

1. Read complete task: description, ACs, test plan, interfaces, docs and files
   touched. Verify provided/consumed dependency interfaces exist with exact
   types, signatures and behavior before implementing. Mismatch blocks; no guesses.
2. Read project docs and AGENTS conventions. Scope searches to relevant paths,
   excluding node_modules/.git/dist/build/.next/__pycache__/.worktrees. For
   large files (>200 lines), locate relevant ranges and use offset/limit rather
   than whole-file reads. Scope/exclude noise explicitly in Explore dispatches.
3. Implement only assigned scope. Read path discipline below before unclaimed
   siblings. A failed replacement may already be applied: reread desired state,
   accept verified no-op, never blindly retry the same stale edit.
4. Write/run specified tests and update every required doc. Use dispatched
   Project Test Commands (Quick/Full/E2E); only if absent use file-based discovery.
   Diagnose failed tests in isolation; fix current-item regressions.
5. Commit coherent units, then immediately check `git -C {worktree-path} status
   --porcelain`. Stage/commit omitted related generated/test/config/untracked
   files before next unit. Write required progress note. No task-dirty exit;
   crash auto-commit is only a safety net. Low turns: commit partial work and
   say what remains.
6. Verify every AC and all pre-submit checks before claiming completion.

## Verification execution

Capture long output once, inspect that capture instead of rerunning for failure
lines. Read `.claude/agents/references/engineer/large-output.md` before large test/command
output (capture, size-aware extraction, replay summaries and Read recovery).

```bash
_tmp=$(mktemp /tmp/yoke-test.XXXXXX)
<project test command> >"$_tmp" 2>&1; _rc=$?
tail -50 "$_tmp"
rg -n 'FAIL|ERROR|error' "$_tmp" || true
exit "$_rc"
```

No tracked `.sh` test runners. For long checks use `yoke watch pytest -- <args>`;
merge shapes `yoke watch merge --print-streaming-pair done-transition <args>` /
`merge-worktree <args>`, then execute printed command once. The selected harness
wait shape governs: wrappers preserve complete raw output, print actionable
terminal failures/results, and pytest streams progress. After exit inspect
`tail -80 <raw-capture>` once, or supplied `--raw-capture` path.

For Yoke change-scoped checks: `yoke watch pytest --impacted main --bounded`.
Contract floor remains; unbounded selection is reported, not silently widened.
QA case owns one full execution for that tree; protected CI owns full sweep.
With `ci_workflow_file`, commit first: runner pushes exact lane candidate and
dispatches CI; dirty/base-branch trees refuse. `--local` is a small targeted
check expected within about one minute, or declared machine-specific/offline
debugging, never justification for a slow dirty-tree suite. Local xdist uses
machine-wide budget. If an eligible local check exceeds a minute, interrupt
cleanly, keep incomplete capture, commit and continue on CI. Continue yielded
CI/watcher handles to exit; never interrupt CI or start beside a live command.

## Pre-Submit Verification Checklist

All checks must pass before final structured output/reflection:

1. `test_plan`: cite commands passed after last relevant change; rerun only
   affected checks. SKIP only if task genuinely has no Test Plan; note absence.
2. `files_touched`: verify specified files, recheck changed ones; implement
   omissions or explicitly justify intentional skips in output.
3. `edited_tests`: after final implementation run every edited test file
   directly using appropriate project runner. Identify test_*.py, *.test.*,
   *_test.*, *.spec.* and other project patterns. No edited tests permits SKIP.
4. `clean_worktree`: mandatory final `git -C {worktree-path} status --porcelain`.
   Commit all related modified/untracked/staged files, write progress note,
   recheck empty. Noncommittable generated/ignored files require explicit
   justification. Never emit reflection with unexplained dirty task files.

## Required Submission Receipt Block

Final epic progress-note DB body contains this exact block. Parent conduct
reads that durable owner, not Agent-result prose; optional chat repetition
does not replace it.

```text
---SUBMISSION-CHECKS-START---
test_plan: PASS | SKIP - <commands/evidence or why absent>
files_touched: PASS | SKIP - <verified coverage or why absent>
edited_tests: PASS | SKIP - <edited files run or none>
clean_worktree: PASS - git -C {worktree-path} status --porcelain is empty
progress_notes: PASS | SKIP - <epic note evidence or allowed skip>
file_budget: PASS | SKIP - <authored files <=350 lines or no created/grown code>
---SUBMISSION-CHECKS-END---
```

Use exact keys. Clean tree has no SKIP. Test-plan/files-touched SKIP needs absent
section; edited-tests SKIP needs none. Progress-notes PASS for epic attempts with
new commits, SKIP only non-epic/no-new-commit attempts. File-budget PASS whenever
authored code created/grew and every authored file <=350; SKIP only no such code.
Missing/malformed/FAIL/UNKNOWN fields redispatch same attempt; missing block or
non-PASS clean_worktree result blocks the item from advancing to validate.

## Path claims, file budget and progress

Edit claimed paths only; widen/escalate every required uncovered file, never
descope. Before touching one, read
`.claude/agents/references/engineer/path-claim-discipline.md`. File Budget and path claims
are independent. Enabled budget: read parent **File Budget** before creating/
growing files; disabled: dispatched scope applies without inventing a budget.
Universal authored limit350, design<=300, owned by `yoke_core.domain.file_line_check`.
Check `yoke check file-line --base main`.
Split oversized files; never --no-verify. Report enabled-budget mismatch to parent.

After each epic commit write `epic_progress_notes` via registered command; DB
renders parent body and syncs issue. Final attempt note is submission receipt:

```bash
yoke workflow-item epic-progress-note append --epic {epic-ref} \
  --task-num {task-num} --note-num {note-num} --body-file <absolute-note-file>
```

Note includes task/update, ISO timestamp, commit, summary and changed files.
Use designated scratch. Current-state checkpoint records objective, decisions/
holds, active work, blockers, next action and durable links, not historical dumps.


## Pack and subprocess procedures

- Reusable scripts/workflows/deployment/infra belong in focused immutable
  versioned `packs/<slug>/`; installed files are project-owned. Project values
  belong DB capability/settings or project .yoke policy. Publish improvements
  as new versions, preview three-way updates preserving customizations; no
  product-source project output, drift policing/pruning/whole-project sync.
- Before subprocess additions, verify registered packet/project command exists.
  Missing surface stops and reports gap, never invented internal module recipe.
  Match local subprocess environment propagation for required settings and
  note justified deviations. Verify actual capability before asserting it.
