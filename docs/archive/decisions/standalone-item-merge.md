# The standalone-item merge boundary

## The gap

A *standalone item* is a backlog item that owns its own implementation branch
directly, with no epic and no generated task graph — every Dash and Blitz item,
and any Issue whose workflow declares `generated_children=none`.

Before this decision there was no named operation that merged one. The two
existing surfaces both refused the job:

- The merge engine (`yoke_core.engines.merge_worktree`) is lane-oriented. Its
  preparation step raised outright for a branch that resolved to an item with
  no epic id, unless the caller had exported `YOKE_DONE_TRANSITION=1` first.
  The permission to merge a standalone branch was therefore an ambient
  environment variable rather than an argument, and the refusal message pointed
  callers at a module path instead of a command.
- The done-transition engine (`yoke_core.engines.done_transition`) does merge
  standalone branches, but it owns the terminal status flip itself and writes
  `status=done` through a path that bypasses the item's workflow gates and its
  QA requirements. For a workflow whose terminal transition is gated on
  execution evidence, that ordering is inverted: the status lands before the
  evidence that is supposed to authorize it.

With no operation in between, agents executing a standalone item fell back to
hand-authored `git checkout main && git merge` in the main checkout. The
observable cost is recorded in the control plane: standalone items reached
`done` with `merged_at` unset, with no `MergeEngineStarted` /
`MergeEngineSucceeded` events, and with no merge lock ever taken — so two
sessions could merge into the same branch concurrently.

## The decision

**One operation owns the standalone-item merge boundary**, and every path that
merges a standalone branch routes through it:
`yoke_core.domain.standalone_item_merge.merge_standalone_branch`.

The operation owns the full ordering, in this order:

1. Resolve the item, its project, its checkout, and its base branch over the
   transport-aware dispatcher, so the same call works against an in-process
   local control plane and against an https server.
2. Verify the calling session holds the item work claim.
3. Merge the branch through the merge engine, passing the standalone
   permission as an explicit argument.
4. Resolve the implementation commit and the resulting merge commit.
5. Stamp `items.merged_at`.
6. Publish the merged base branch when the checkout has a remote.
7. Emit the merge outcome to the events ledger.

Everything above the merge is bookkeeping the merge itself produces, so it
belongs to the merging operation. Everything below it — recording execution
evidence, syncing the item to GitHub, and flipping the lifecycle status — is
*item* bookkeeping that differs by workflow, so it stays with the caller:

- `yoke merge item` (the operator/agent surface) continues through evidence,
  GitHub sync, and the terminal lifecycle transition, which runs the workflow's
  own gates rather than bypassing them.
- `done_transition` keeps its own post-merge sequence for workflows with task
  graphs, but no longer reaches for an environment variable to be allowed to
  merge.

### Why the permission became an argument

`YOKE_DONE_TRANSITION=1` encoded "the caller is the done-transition engine".
What the merge engine actually needs to know is narrower and stateless: *this
branch belongs to an item, not an epic, and the caller accepts that*. That is
`MergeArgs.standalone`. An argument is inspectable, testable, and cannot leak
into an unrelated subprocess the way an exported variable can.

### Why the status flip stays with the caller

The terminal transition is the only place a workflow's gates run. Moving it
inside the merge operation would either duplicate gate knowledge or reproduce
the bypass this decision exists to remove. Instead the merge operation returns
the merge identity, the caller records evidence with it, and the caller then
asks the lifecycle interpreter to transition — which passes only if the
evidence gate and any selected posture gate are satisfied. Deployment posture
falls out for free: the transition simply refuses until the item-bound
deployment run has succeeded, and the caller retries.

### Why direct merge is the default

The operation merges the branch into the base branch locally and then pushes,
rather than opening a pull request. A standalone item is instruction-sized work
that a single session already verified; a review round trip adds latency
without adding a reviewer. Projects that require pull requests are served by a
per-project mode knob, which is not part of this decision.

## Portability

The operation must behave identically for a source checkout of Yoke itself and
for an unrelated project that installed Yoke and has only the `yoke` CLI on
its PATH. Three constraints follow:

- **No control-plane reads or writes outside the dispatcher.** Every item,
  project, claim, evidence, and lifecycle touch goes through
  `call_dispatcher`, never a direct connection, so an https-connected project
  relays them to its server.
- **No assumption about the checkout.** The repo root comes from the project's
  machine-local checkout mapping and the base branch from the project row, not
  from the current working directory or a hard-coded `main`.
- **No assumption about GitHub.** A project whose sync mode is disabled skips
  the item sync entirely instead of failing the merge, and a checkout with no
  remote skips the push.

The merge lock is the sharpest case. It is control-plane state, so opening a
local connection for it — as the engine did — fails outright on an
https-connected machine, leaving concurrent merges unserialized on exactly
the transport most sessions use. The lock is therefore split: its row
operations relay through the dispatcher, while holder liveness stays on the
client, because the process holding a merge lock is the local merging
process and the server's process table says nothing about it.

## Consequences

- The refusal message in the merge engine now names a command rather than a
  module path, and it fires only when a caller genuinely omitted the standalone
  permission.
- Hand-authored merges of a standalone branch are retired: the Dash and Blitz
  skills name one command, and that command is the only teaching surface.
- The merge lock is taken for every standalone merge, which it previously was
  not. The lock remains global rather than scoped per project and target
  branch; scoping it is a separate change to a shared coordination primitive.
