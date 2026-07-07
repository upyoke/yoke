---
name: merge
description: Sequentially merge all worktree branches for an epic into main via PR + CI + merge. Use --audit for pre-merge readiness assessment.
argument-hint: "{epic-id} [--audit] [--skip-simulation]"
---

# Internal sub-skill -- called by usher. Not operator-facing.

# /yoke merge {epic-id}

Merge all completed worktree branches for an epic into the target branch (usually main), one at a time.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug not worth a ticket, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Arguments

- `{epic-id}` — Epic ID (the numeric `id` of the epic backlog item in the DB). Optional when `--audit` is used without an epic scope.
- `--audit` — Run a read-only pre-merge readiness assessment instead of merging. See [Audit Mode](#audit-mode) below.
- `--force-lock` — Force-clear any existing DB merge lock before acquiring a new one. Use when a previous merge session crashed and left a stale lock that was not auto-detected. Passed through to the retained merge watcher, `python3 -m yoke_core.tools.watch_merge merge-worktree`.
- `--skip-simulation` — Override the integration simulation gate for epics. Use only when the operator explicitly wants to merge without a canonical integration simulation record.

## Philosophy

**Be the giant.** We stand on inherited shoulders; leave a leg up for the next agent by making this artifact cold-start complete. Merge is the final handoff from parallel work into shared history, so its audit output and failure diagnostics must be specific enough for a clean retry.

**Rollback clarity beats merge heroics.** If the merge is not safe, stop with exact blockers, branch state, and recommended recovery. Do not trade auditability for clever recovery steps that future sessions cannot reconstruct.

## Audit Mode

When `--audit` is passed (with or without an `{epic-id}`), the merge skill runs a **read-only** pre-merge readiness assessment instead of the normal merge flow. This replaces ~10 manual commands with a single report.

### Usage

```
/yoke merge --audit # Audit all epics with unmerged branches
/yoke merge {epic-id} --audit # Audit only one epic's branches
```

### What the audit reports

For each epic with unmerged worktree branches:
- Epic ID, title, item status
- Task completion: N/M completed, with incomplete tasks listed
- Branch details: commits ahead of main, worktree dirty state
- Integration simulation status (CLEAN, GAPS FOUND, or MISSING)
- Item status mismatches (all tasks are terminal-success but the epic was not advanced)
- Recommended merge order based on task dependencies
- Standalone `YOK-*` branches with status `done`
- Potential cross-branch conflicts (via `git merge-tree`)

### Execution

When `--audit` is detected, run the audit engine and **exit** — do not proceed to the merge flow:

```bash
yoke merge audit {epic-id-if-provided}
```

The engine is completely read-only. It does not modify DB state, git state, or GitHub state.

---

## Phases

When `--audit` is NOT passed, merge executes five phases in order. Each phase lives in its own file; read and execute them in sequence.

### Argument validation
Read `.agents/skills/yoke/merge/argument-validation.md` and execute it. Runs epic lookup via DB and bare-item-ref detection. Stops immediately if the argument does not resolve to a known epic with tasks.

### Preflight (Steps 1–5)
Read `.agents/skills/yoke/merge/preflight.md` and execute it. Requires a canonical integration simulation (unless `--skip-simulation`), verifies epic-level acceptance criteria scoped to worktree paths, confirms every epic task has reached terminal success, reads the worktree plan, and determines the merge order.

### Per-branch merge loop (Step 6)
Read `.agents/skills/yoke/merge/merge-loop.md` and execute it. For each branch: resolves the actual checked-out branch, commits any uncommitted Tester artifacts, invokes `python3 -m yoke_core.tools.watch_merge merge-worktree`, updates task statuses to `done`, syncs local main, re-verifies ACs against main, and halts on regression.

### Post-merge bookkeeping (Step 7)
Read `.agents/skills/yoke/merge/post-merge.md` and execute it. Syncs local main with origin via stash-pull-pop, closes the epic GitHub issue, advances the linked backlog item to `done` (if not already), and sets `merged_at`.

### Conflict handling (exit 3 / exit 1) + Notes
Read `.agents/skills/yoke/merge/conflict-handling.md` when `python3 -m yoke_core.tools.watch_merge merge-worktree` exits with code 3 (agent-resolvable conflicts) or code 1 (hard conflicts, test failures, push/CI failures). This file also captures the operational Notes about sequential merge ordering, auto-resolved generated files, CI timeouts, and `--force-with-lease` push semantics.
