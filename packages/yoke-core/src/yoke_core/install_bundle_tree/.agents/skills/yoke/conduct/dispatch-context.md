# Conduct — context assembly

## Section Index

Safe-read guidance: load only the named owner/heading with offset/limit. The
router owns phase order; this index owns dispatch inputs and utilities.

| Step | Owner |
|---|---|
| Sync, Epic Fan-Out Enumeration, activation | [entry-activation-resolution.md](entry-activation-resolution.md) |
| Plan gap, provider contracts, post-Engineer submission | [dispatch-context-gates.md](dispatch-context-gates.md) |
| Project context and QA roster | [dispatch-context-project.md](dispatch-context-project.md) |
| Capability-based preview and Browser QA | [dispatch-context-ephemeral.md](dispatch-context-ephemeral.md) |
| Prior attempts | [dispatch-context-rehydrate.md](dispatch-context-rehydrate.md) |
| Parallel dispatch/merge/chain advance | [dispatch-context-dispatch.md](dispatch-context-dispatch.md) |
| Engineer cold prompt and Tester diff preparation | [dispatch-context-prompts.md](dispatch-context-prompts.md) |
| Minimal Tester output retry | [dispatch-context-prompts-minimal.md](dispatch-context-prompts-minimal.md) |
| Exhausted Tester fallback | [dispatch-context-verify.md](dispatch-context-verify.md) |
| Reflections, review artifacts, QA lifecycle | [dispatch-context-artifacts.md](dispatch-context-artifacts.md) |

## Prepare exact parent/task context

```text
yoke items get PREFIX-N spec
yoke workflow-item epic-task body-get --epic PREFIX-N --task-num {task_num}
yoke workflow-item epic-dispatch-chain get --epic PREFIX-N --worktree {BRANCH} --json
yoke item-worktrees list PREFIX-N --json
```

Parent public ref is not a local task number or items.id. Retain _task_ids and
each _worktree_path_${_task_id}/_worktree_branch_${_task_id}. Use registered
chain/lane rows, never inferred directories. Missing lane record stops for
path-record/operator repair. Metadata idempotently records all three resolved
worktree/branch/worktree_path fields through the registered task adapter.
Sync/filters/activation reuse the entry owner; no duplicate freshness algorithm.
Advance only pinned lifecycle stages; legacy root DB files halt investigation.

Cold prompt includes parent ref/title/project and internal id only when a
source-dev owner requires it; local task number/title and resolved GitHub issue;
exact registered lane/branch/MAIN_ROOT; task and parent spec read commands;
dependency interfaces/downstream task bodies; project docs/test commands;
materialized QA and preview URL/branch/SHA; baseline/diff captures; active
coverage and prior attempt evidence. Code/tests/docs belong in that lane.
Control-plane state uses registered Yoke surfaces, never MAIN_ROOT/data or a
worktree DB. Notes/reviews use epic-progress-note append/review-insert.

Project-owned context includes Yoke itself. Always run capability-based preview
independently when declared; refresh its URL after preparation. Before Engineer,
rehydrate. After each return capture reflections and durable artifacts before
verdict/chain processing. Cleared task context is rebuilt on every chain advance.
