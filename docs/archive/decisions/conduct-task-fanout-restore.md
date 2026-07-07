# Conduct task-level fan-out — restore

## Decision

Restore conduct's task-level parallel fan-out within an epic. Within a single
`/yoke conduct` invocation against an epic, conduct enumerates every chain
whose head task is `planned` with satisfied dependencies, filters out
candidates that fail same-worktree or dependency checks, and dispatches one
Engineer per surviving candidate in a single Agent-tool batch. The same
parallel pattern applies to the Tester pass that follows.

The `5g. Parallel Engineer Dispatch` and `5i. Parallel Tester Dispatch`
prose in `dispatch-context-dispatch.md` and `dispatch-context-prompts.md`
becomes the live execution path for batches with more than one dispatchable
task. The single-task path through `engineer-tester-dispatch.md` remains the
degenerate case for fan-out batches of size one.

## Why restore (not remove)

- **Default per AC-8.** The ticket's acceptance criteria explicitly default
  to restore. Removal requires concrete evidence that fan-out was
  intentionally retired; "smaller diff" is not sufficient rationale.
- **Observed regression.** YOK-1577 ran with 14 epic tasks across 12
  independent worktrees. Four tasks were dependency-clean and in distinct
  worktrees at dispatch time (tasks 2, 3, 5, 14). conduct dispatched only
  one Engineer (task 14), then stalled when that Engineer hit a stream-idle
  timeout. Three independent tasks sat idle waiting for an unrelated chain
  to clear.
- **Orphaned but live prose.** `dispatch-context-dispatch.md` (sections 5g,
  5i) and `dispatch-context-prompts.md` ("Dispatch ALL Engineers in
  parallel") were preserved during the YOK-1214 phase-file split. No commit
  in that history removed the parallel path or its rationale; the entry
  rewrite simply stopped routing through it. This is the asymmetry the
  bug report flagged: the dispatch protocol still describes parallel
  fan-out, but no live entry path invokes it.
- **No structural blocker.** Same-worktree protection (S6d) already
  prevents two tasks from clobbering one worktree. Dependency verification
  (S6e) runs per candidate. Work claims and dispatch-chain state guard the
  cross-task invariants. Fan-out across distinct worktrees with satisfied
  deps is safe today.

## What this slice changes

- `entry-activation-resolution.md` S6c enumerates every dispatchable head
  task into `_task_ids` (newline-separated), filters via same-worktree and
  dependency checks per candidate, and explains exclusions instead of
  silently picking one.
- `entry-activation-resolution.md` S6f activates each task in `_task_ids`
  (status, worktree fields, baseline) inside a loop. The activation
  comment moves from "Dispatched by conduct (single-item)" to
  "Dispatched by conduct (task fan-out)" so progress notes carry honest
  provenance.
- `entry-activation.md` S4/S6 rename "Epic Single-Item Flow" to
  "Epic Task Fan-Out Flow".
- `engineer-tester-loop.md` routes batches with more than one task to the
  parallel pathway in `dispatch-context-dispatch.md` /
  `dispatch-context-prompts.md`. Single-task batches keep the existing
  `engineer-tester-dispatch.md` → `engineer-tester-closeout.md` path
  unchanged.
- `runtime/api/test_skill_doc_regressions_conduct_core.py` adds a
  regression class that asserts the entry path enumerates multiple
  candidates, the parallel pathway is reachable from the loop, the
  task-scope rename landed, and the legacy single-item routing wording
  no longer appears in conduct prose.

## What stays out of scope

- The YOK-368 batch-parallel design itself is not re-litigated. The 5g/5i
  prose stays as the per-batch execution protocol; conduct is restored to
  call it.
- Tester-side parallelism mirrors the Engineer-side decision and uses the
  existing `5i. Parallel Tester Dispatch` protocol with no template
  changes.
- Cross-epic fan-out (multiple `/yoke conduct` invocations across
  epics) remains supported via separate sessions; nothing in this slice
  changes that.
- The YOK-1577 lane-preservation fix (commit `efe2fd421`) is preserved:
  S6c reads `worktree`, `worktree_path`, and `branch` from each chain,
  and S6f persists those fields on each activated task without
  collapsing them to `YOK-{N}`.

## Vocabulary

`single-item` is reserved for the item-scope statement: conduct processes
one backlog item per invocation. Task-scope language uses `task`,
`task fan-out`, and `task chain`. The file `single-item.md` keeps its
name because it documents the item-scope mode. Section names that used
to read `Epic Single-Item Flow` become `Epic Task Fan-Out Flow`.
