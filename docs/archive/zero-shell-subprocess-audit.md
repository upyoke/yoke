# Zero-Shell Subprocess Audit

**Owning ticket:** YOK-1362
**Scope added:** 2026-04-10 (after the YOK-1350 usher incident)
**Methodology:** static AST scan across every Python owner that replaced a
shell entrypoint during the zero-shell migration, followed by manual
classification of each unchecked `subprocess.run` / `subprocess.Popen` site.

## Why this document exists

YOK-1350 landed a production regression because `merge_worktree.py` —
freshly migrated out of shell by YOK-1337 — ignored the return codes of
`gh pr create`, `gh pr checks`, and `gh pr merge`. It printed
`Successfully merged ...` twice while GitHub was actively refusing the PR
merge, then fell through to `gh pr merge ""` on retry because `pr_num` was
empty but never validated.

YOK-1362 fixed the merge engine end-to-end (fresh target validation,
fail-fast subprocess handling, existing-PR reuse, truthful success output,
17 merge lifecycle events, 8 regression tests). But `merge_worktree.py` is
one of dozens of Python owners. The same class of bug — unchecked
subprocess return codes, silent fallthrough after failure, continuation
with empty identifiers — can exist in any engine migrated out of shell
without audit discipline.

This document is the audit YOK-1362 expanded into scope to close that gap.

## Method

A small AST scanner walked these 29 owners and collected every
`subprocess.run` / `subprocess.Popen` / `subprocess.check_*` call:

**Engines (`yoke/api/engines/`):**
`merge_worktree.py`, `done_transition.py`, `resync.py`, `merge_audit.py`,
`repair_status.py`, `doctor.py`

**Domain (`yoke/api/domain/`):**
`agent_stop.py`, `session_hooks.py`, `bash_complete.py`, `hook_helpers.py`,
`epic_task_sync.py`, `deploy_pipeline.py`, `backlog_github_sync.py`,
`backlog.py`, `browser_client.py`, `browser_qa.py`, `migration_harness.py`,
`backup.py`, `github_actions.py`, `project_renderer.py`, `gh_retry.py`,
`gh_issue.py`, `db_error_hook.py`, `conduct_reviewed_handoff.py`,
`persist_simulation.py`, `bootstrap_project.py`, `deploy_qa_recorder.py`,
`events_crud.py`, `update_status.py`

For each site the scanner asked: within the enclosing function, is the
return value's `.returncode` inspected, does the call pass `check=True`, or
is the result wired into a `raise ...`? Anything that answered "no" was
flagged as **mechanically unchecked**. Every mechanically-unchecked site was
then classified by hand into one of four categories:

1. **HELPER PASSTHROUGH** — the call is inside a small wrapper (`_run_git`,
   `_run_shell`, `gh_retry.run_gh`) that returns the `CompletedProcess` and
   expects the caller to inspect it. Not a risk at the helper; risk moves to
   each caller and is covered by the caller's classification.
2. **INTENTIONAL FIRE-AND-FORGET** — telemetry emitters, best-effort
   post-merge sync calls, board rebuilds, and similar non-lifecycle side
   effects where a subprocess failure must never break the parent flow.
   These should still be wrapped in a `try`/`except` and should never log a
   false success, but a return-code check is not required.
3. **BACKGROUND LAUNCH** — `subprocess.Popen(...)` calls that start a
   long-running daemon or hand-off process. `.returncode` is not available
   at call time by design.
4. **AT-RISK** — lifecycle-affecting calls where a silent failure would
   either produce a false success, leave state ambiguous, or advance an
   item into a bad status. These need a fix.

## Headline numbers

| Scope | Count |
|---|---|
| Files scanned | 29 |
| Total subprocess sites | 115 |
| Mechanically checked (`returncode` or `check=True`) | 69 |
| Mechanically unchecked (needed manual classification) | 46 |
| **AT-RISK after manual classification** | **3** (all fixed in YOK-1362; see below) |

## Classification of unchecked sites

### AT-RISK — fixed in YOK-1362

**1. `merge_worktree.py::_wait_for_ci` — `gh pr checks` polling (lines 1655, 1668)**

The CI poll loop inspected only `result.stdout.strip()`. A non-zero `gh`
exit with empty or unparseable stdout was treated as "no CI configured —
skip", which silently bypassed the CI gate.

**Fix (YOK-1362):** the initial quick-check and every poll iteration now
check `result.returncode != 0` first and route failures through
`_fail_merge_subprocess(..., event_name="MergePullRequestCiFailed")` so the
engine returns exit 1 with an actionable stderr block and an ERROR-level
event in the ledger.

**2. `merge_worktree.py::do_pr_merge` — `gh pr create` (line 1457)**

(Already fixed during the main YOK-1362 work — listed here for completeness.)
The old code parsed `pr_url` from stdout and then called `gh pr merge
"$pr_num"` without checking `pr_result.returncode`, allowing empty
identifiers to reach `gh pr merge`.

**Fix (YOK-1362):** `do_pr_merge` now checks `pr_result.returncode`,
intercepts "already exists" stderr and reuses the existing PR via
`_discover_existing_pr`, and hard-fails on empty `pr_url` / `pr_num` via a
defensive `pr-identifier-validation` phase. Covered by
`test_sun1362_pr_create_hard_fail_no_merge`,
`test_sun1362_empty_pr_url_never_merges`,
`test_sun1362_existing_pr_reused`,
`test_sun1362_existing_pr_unresolvable`.

**3. `merge_worktree.py::do_pr_merge` — `gh pr merge` (line 1621)**

(Already fixed during the main YOK-1362 work.) The old code printed
`Successfully merged ...` before checking the merge subprocess result.

**Fix (YOK-1362):** `do_pr_merge` now checks `merge_proc.returncode` and
routes failures through `_fail_merge_subprocess(...,
event_name="MergePullRequestMergeFailed")`. The "Successfully merged" line
moved into `_post_merge_cleanup` after the origin-ancestry verification
(AC-4). Covered by `test_sun1362_pr_merge_failure_no_false_success`.

### HELPER PASSTHROUGH — not a risk at the helper

The following generic wrappers return `CompletedProcess` for the caller
to inspect and do not need `check=True`:

| File | Line | Helper |
|---|---|---|
| `merge_worktree.py` | 111 | `_run_git` |
| `merge_worktree.py` | 133 | `_run_shell` |
| `done_transition.py` | 93 | `_run_git` |
| `done_transition.py` | 109 | `_run_shell` |
| `doctor.py` | 1069 | internal `_run` |
| `doctor.py` | 1137 | internal `_run` (with env) |
| `repair_status.py` | 116 | `subprocess` helper (`check=False` explicit) |
| `repair_status.py` | 117 | `subprocess` helper (`check=False` explicit) |
| `gh_retry.py` | (core) | `run_gh` returns result; callers inspect |
| `gh_issue.py` | (core) | `run_gh_*` returns result; callers inspect |
| `events_crud.py` | (2 sites) | lint-hook invocation wrapper |
| `hook_helpers.py` | (2 sites) | path-resolution helpers |

Risk for each of these is re-anchored to the CALLER. Callers in the
classified set above all check `.returncode` or explicitly fire-and-forget.

### INTENTIONAL FIRE-AND-FORGET — documented and safe

| File | Sites | Purpose | Notes |
|---|---|---|---|
| `update_status.py` | 203, 423, 456 | `emit-event.sh`, rebuild-board, sync-to-github | Telemetry / view regen; must never block a state mutation |
| `session_hooks.py` | 268, 921 | `service_client.py session-begin`, `AgentSessionStarted` emit | Best-effort session tagging |
| `deploy_pipeline.py` | 48, 73, 704 | executor dispatch with `timeout=`, DB updates | Executor results routed via DB, not the subprocess return |
| `deploy_qa_recorder.py` | 42, 49 | `qa run-add` emissions | Recorder is eventually-consistent, non-blocking |
| `browser_qa.py` | 181, 501 | curl probe, `qa run-complete` | Probe result read from stdout; run-complete telemetry |
| `bash_complete.py` | 131 | `sync-progress.sh` | Best-effort epic progress sync |
| `backlog_github_sync.py` | 674 | regenerate-view; `check=False` is EXPLICIT | Intentional |
| `migration_harness.py` | 200 | `emit-event.sh` | Telemetry |
| `db_error_hook.py` | 313 | `emit-event.sh DataLossDetected` | Telemetry (already FATAL-severity) |
| `conduct_reviewed_handoff.py` | 120 | status update | Epic-level status update, retry loop upstream |
| `bootstrap_project.py` | 147 | interactive shell passthrough | Operator tool, not a lifecycle path |
| `epic_task_sync.py` | 120 | `gh_retry` passthrough | Caller inspects result |
| `agent_stop.py` | 71, 103 | `git status --porcelain`, `git commit` | Auto-commit flow; absence of changes is the signal, not returncode |

All of these are low-signal: a failure cannot produce a false success in
the parent lifecycle because the parent does not treat the subprocess
result as a source of truth.

### BACKGROUND LAUNCH — Popen is correct here

| File | Line | Purpose |
|---|---|---|
| `browser_client.py` | 302 | Playwright daemon launch (detached) |
| `agent_stop.py` | 178 | `yoke-db.sh epic progress-note-insert` background emit |

These `subprocess.Popen` calls are intentionally backgrounded — checking
`.returncode` would require `.wait()` which is exactly what the caller is
avoiding.

### One outstanding minor finding NOT fixed in YOK-1362

**`merge_worktree.py::_resolve_additive_conflict` — `git merge-file --union`
(line 864)**

This is inside the additive-conflict auto-resolver. A non-zero exit from
`git merge-file --union` is currently swallowed and the caller assumes
the conflict was resolved. In practice `git merge-file --union` rarely
fails on well-formed inputs, and the trial merge guard upstream catches
the structural cases that matter most. This is a latent low-signal bug —
worth tracking as a follow-on, but outside the scope of YOK-1362's "merge
path fail-fast" charter.

**Recommended follow-on (not filed in this session per operator decision):**
add a returncode check to `_resolve_additive_conflict` and emit a
`MergeAutoResolveFailed` event on failure, so the conflict auto-resolver
cannot silently produce a broken merge.

## What this audit does NOT cover

- Test files — intentionally excluded. Test subprocess calls are driven
  by the test harness and failures surface as pytest failures.
- `yoke/api/board/` — pure rendering, no lifecycle subprocess usage.
- `yoke/api/main.py` — FastAPI entrypoint; no subprocess calls.
- Helper modules with zero subprocess usage — skipped by the scanner.
- The 46 mechanically-unchecked calls that passed manual classification
  are listed inline above but not re-enumerated here. Re-run the audit
  script at the end of this document to reproduce.

## Reproducing the audit

The scanner lives in this doc rather than as a standalone script because
the methodology is ad-hoc and the output is primarily for humans. To
re-run it:

```python
import ast
from pathlib import Path

TARGETS = [
    "yoke/api/engines/merge_worktree.py",
    "yoke/api/engines/done_transition.py",
    # ... (see "Method" section above for full list)
]

# For each target, parse with ast.parse(), walk for Call nodes whose func
# is subprocess.run / Popen / check_*, then ask: does the enclosing
# function body contain .returncode within ~12 lines after the call, or
# does the call pass check=True?  Everything else is mechanically unchecked
# and needs manual classification.
```

The full scanner source used for the 2026-04-10 audit is preserved in the
YOK-1362 session transcript and the YOK-1362 branch history.

## Keeping this audit honest going forward

- **New engines:** any future zero-shell migration must either audit its
  own subprocess sites or update this document.
- **Hook:** consider a `lint-subprocess-returncode.py` PreToolUse hook that
  flags new unchecked `subprocess.run(...)` calls in diffs touching
  `yoke/api/engines/**` and `yoke/api/domain/**`. Not in scope for
  YOK-1362 but a natural extension.
- **Periodic refresh:** re-run the scanner at the end of each zero-shell
  wave and append a dated delta section to this document.
