## Path Tracing Beyond the Task

Before test selection trace actual exports (named/default, argument/return types,
optional fields), runtime files/env/services/cwd assumptions and downstream
Expects, not just own Provides. Put integration concerns in Path Tracing:
informational warnings do not change binary verdict, concrete blockers do.

## Prose-only triage

Read `git -C {worktree-path} diff main...HEAD --name-only`, or dispatched
TASK_BASELINE..HEAD for task scope. Only .md allowlist (or empty diff) permits
skipping ordinary full executable suite; no-extension/config/code files do not.
Keep all AC/interface/documentation/contract verification; Markdown prompts and
generated instructions may still have runtime contract tests. Record exact
scope and skipped suite in Regression Analysis, never broaden allowlist without
evidence. Any other file requires risk-based selection.

## Project Test Commands

Use nonempty dispatch Quick/Full/E2E commands over guessed file discovery:
Quick for narrow checks; Full for broad/no-regression risk; E2E below only.
Absent/empty block falls back to scoped tests. Do not duplicate discovered tests
unless project command coverage is insufficient; record source/exclusions in
Test Commands Used.

## Ephemeral E2E

After passing unit/integration checks only. If already failed, overall FAIL,
skip E2E. Need nonempty/non-none Ephemeral URL AND configured E2E command;
absence skips gracefully with exact reason (no URL/no E2E command).
Run dispatched command with `BASE_URL={ephemeral_url}` injected. Nonzero E2E
blocks even when lower-level tests pass. Report failing names/assertions and
screenshots/traces/videos (e.g. test-results/playwright-report) with actual paths.
