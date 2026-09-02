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

The engine's own command line still accepts that permission as a flag, and a
run reached that way is only half the boundary: it lands the branch, prints
`Successfully merged`, and leaves the item without evidence, without a GitHub
sync, and short of its terminal transition. Because every sanctioned caller
drives the engine in-process, the flag on the command line is refused unless a
one-shot ceremony nonce is spent — the same mechanism that guards a bare
`status=done` write, sharing its implementation rather than resembling it. The
refusal names `yoke merge item` and `/yoke usher`; an operator who means to run
the engine alone spends a nonce.

### Why the status flip stays with the caller

The terminal transition is the only place a workflow's gates run. Moving it
inside the merge operation would either duplicate gate knowledge or reproduce
the bypass this decision exists to remove. Instead the merge operation returns
the merge identity, the caller records evidence with it, and the caller then
asks the lifecycle interpreter to transition — which passes only if the
evidence gate and any selected posture gate are satisfied. Deployment posture
falls out for free: the transition simply refuses until the item-bound
deployment run has succeeded, and the caller retries.

### Why queue landing and close-out are separate

A project with merge-queue capability opens and arms a pull request, records a
durable item marker, and returns immediately. The queue owns the long CI wait;
no detached local waiter owns item state. A control-plane observer notices the
merge and messages the live claim holder, whose re-entry records evidence and
runs the terminal lifecycle transition. That re-entry sees a branch the base
already contains, but the durable marker keeps it on the queue close-out path:
it records the identified merge-group run as the item's `ci_run` proof before
execution evidence is evaluated. It never republishes the lane or re-enters
the pull request. Missing proof leaves the already-landed item open with a
retry instruction, rather than silently classifying it as a local merge. The
marker makes that handoff visible and idempotent. `--wait` retains the inline
poll only for harnesses and operators whose process lifetime safely spans it.
Projects without merge-queue capability keep the local merge engine.

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

### Why close-out runs on the connected control plane

Merge admission needs a database this process can lock, so the local merge
runtime selects the same-universe local Postgres connection before it loads
the engine. That selection is also, silently, a choice of *which build*
executes the control-plane writes the close-out then makes: a non-https
connection dispatches in-process, so the evidence record and the terminal
transition are resolved by whatever engine the merging process imported.

For a source lane that engine is the code as of the branch's base commit.
A tightened done obligation therefore landed on trunk, deployed to the whole
fleet, and changed nothing about the close-out every Dash actually runs — the
next lane had branched before it, closed its item out under the older
contract, and neither the new stamp nor the new refusal ever executed. The
gate that would have caught the omission was part of the same missing code,
so the item reached `done` reporting success.

The three writes that carry an item's terminal semantics — merge-queue CI
proof, execution evidence, and the transition it authorizes — therefore go
back to the connection the operator selected, restoring the portability rule
above for exactly the calls that decide whether the item is done. Everything
the merge itself needs keeps the local authority the runtime bound for it.

The connected env is bound by the runtime
(`close_out_control_plane_authority.bind_connected_control_plane`) rather than
re-derived in the engine, because the override replaces an explicit `--env`
the operator may have passed; re-reading the machine config would answer with
the default connection and close the item out in the wrong universe. With no
binding the context managers do nothing, so a direct engine call and a
universe that never switched keep the connection they already had.

## Consequences

- The refusal message in the merge engine now names a command rather than a
  module path, and it fires only when a caller genuinely omitted the standalone
  permission.
- Hand-authored merges of a standalone branch are retired: the Dash and Blitz
  skills name one command, and that command is the only teaching surface.
- The merge lock is taken for every standalone merge, which it previously was
  not.
- The lock is scoped to what a merge actually contends for: one target branch
  of one project. It used to block globally, so a merge into one project
  serialized behind an unrelated merge into another. A row with no recorded
  scope — written before the columns existed, or by a caller that could not
  resolve its project — still blocks everything, because "scope unknown" must
  never be read as "scope compatible".
- Queue CI proof, close-out evidence, and the terminal transition are decided
  by the connected control plane's build, so a contract that lands and deploys
  governs the next close-out instead of waiting for every operator's lane to
  be rebuilt.
