## Pre-submit verification checklist

Work through this immediately before submitting. Every item is something a
reviewer will otherwise find for you, at the cost of a round trip.

## Pre-Submit Verification Checklist

**This checklist is MANDATORY before every task submission.** Do not declare a task complete or produce your `---REFLECTION-START---` block until every checklist item below passes. Skipping any check is a submission failure.

### Check 1: Verify Test Plan (evidence-based)

If you already ran the task spec's test plan commands earlier in this session and they passed **after your last code change**, cite that evidence (turn number, result). You do NOT need to re-read and re-run from scratch.

If you made code changes after the last passing test run, re-run only the affected test plan commands. If a command fails, fix the issue and re-run until it passes.

If the task spec has no `## Test Plan` section, skip this check (but note the absence in your structured output).

### Check 2: Verify Files Touched (evidence-based)

If you already verified files touched during implementation, cite that evidence. Only re-verify files you changed after the last check.

For any file in the spec's `## Files Touched` that was not addressed, either implement the missing change or explicitly explain in your structured output why it was intentionally skipped (with justification).

### Check 3: Run Edited Test Files

After all implementation is complete, identify every test file you edited during this task (files matching patterns like `test-*.sh`, `test_*.py`, `*.test.*`, `*_test.*`, `*.spec.*`). Run each one directly and verify it passes:

```bash
# For each test file you edited:
sh path/to/test-file.sh   # or the appropriate test runner
```

If an edited test file fails, fix the issue before submission. If you edited no test files, skip this check.

### Check 4: Clean Worktree Verification

**This check is MANDATORY and cannot be skipped.** Run `git -C {worktree-path} status --porcelain`. If ANY task-related files appear (modified, untracked, or staged), you MUST:

1. Stage and commit them with a descriptive message.
2. Write a progress note for the commit.
3. Re-run `git -C {worktree-path} status --porcelain` to confirm the worktree is clean.

**You MUST NOT produce your `---REFLECTION-START---` block with a dirty worktree.** The safety-net auto-commit is a crash-recovery mechanism, not a normal exit path. Relying on it degrades cold-start quality (no progress note) and creates noisy commit history.

If you cannot commit certain files (e.g., generated artifacts that should be gitignored), explicitly note them in your structured output with justification for why they were left uncommitted.

---
