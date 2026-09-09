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
7. Record the merge outcome on the item's merge receipt document and emit
   the matching telemetry.

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

A project with merge-queue capability opens and arms a pull request, reads
back from GitHub that it is holding the landing, and records a durable item
marker. Admission reads arming, queue membership, eligibility, and required
checks together. Later point-in-time liveness reads use
`yoke github merge-queue readiness PREFIX-N --json`, which composes the pull
request with `mergeQueue(branch).entries` and reports its exact entry state.
GitHub consumes `autoMergeRequest` when the entry forms, so a null field means
`consumed` when an `AWAITING_CHECKS`, `UNMERGEABLE`, or `MERGEABLE` entry exists;
only an absent entry plus absent arming means `cleared`. GitHub creates the
entry only after the pull request's own checks pass, so requiring it at arming
time would refuse ordinary landings, while trusting the mutation alone records
a handoff GitHub never took. The required-check field is what separates the
ordinary wait from a landing that can never happen: `BLOCKED` with everything
still running is armed-and-waiting, and `BLOCKED` with one required check
already red is an ejection wearing the same clothes — read as the former, it
held a worker thirteen minutes on a pull request the queue would never take.
The same read orders the landing, which refuses rather than arming
merge-when-ready onto an already-red pull request. The queue owns the long CI
wait; no detached local waiter owns item state. A control-plane observer reads
the composed state until the landing resolves — merged, or no longer being driven —
and messages the live claim holder either way. A merge notice leads to a
re-entry that records evidence and runs the terminal lifecycle transition; a
stopped notice names the recovery (usually rebase, re-gate, re-run) and clears
the queue admission, because there is no longer a landing to wait for. That re-entry sees a branch the base
already contains, but the durable marker keeps it on the queue close-out path:
it records the identified merge-group run as the item's `ci_run` proof before
execution evidence is evaluated. It never republishes the lane or re-enters
the pull request. Close-out first compares the current lane candidate to the
recorded landing identity; matching it is enough even when a squash is not an
ancestor of the base. New commits after that landing are refused — file a
fresh work item so they get their own merge identity — and the lane is left in
place. Missing proof leaves the already-landed item open with a
retry instruction, rather than silently classifying it as a local merge. The
marker makes that handoff visible and idempotent. The record keeps the named
`queue_holding`, `queue_entry_state`, and `merge_when_ready` outcomes alongside
its terminal classification, evidence, observation time, and semantic-change
time. `--wait` retains the inline process but consumes that record: once per
minute it asks a registered server function to refresh the whole project's
pending landings when the shared cadence is due. The waiting machine performs
no GitHub or git read loop, the machine relay is not the record's only trigger,
and a stale record refuses as `landing_record_stale` with its refresh evidence
and recovery.

A relay-launched session never waits for the landing at all. It is a headless
command whose turn the harness caps well below a queue landing, so the wait it
was told to hold died with the turn anyway — the branch landed, the item stayed
at `reviewing-implementation`, and the watcher that was supposed to close it out
was gone. The landing is already durable before any wait begins, and the
control-plane observer messages the claim holder when it resolves, so the
landing notice re-enters the worker and the same command completes close-out.
Arming and stopping is therefore the shape that matches what such a session can
actually do; the fear that produced the in-turn wait — seven branches landed in
one night with nobody to close them out — was a worker stopping *before* that
notice existed, not the handoff itself.

Every other caller still waits, and the merge watcher chooses its wait shape
from the calling session's manifest wake capability plus current control-plane
reachability, never from executor name or who opened the session. A verified
wake route gets the background subscription; no route or an unknown answer keeps
the same watcher invocation in-turn until close-out.
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

### Why a transition lost to a finished close-out is not a failure

One pull request can be followed to `merged=true` by two watchers of the
same session when the merge command is dispatched twice. Both enter
close-out. The first records evidence, moves the item to `done`, and
releases the work claim; the second records evidence and is then refused
the terminal transition, because the claim it verified at admission is
gone. Reported verbatim, that refusal carried the dispatcher's recovery —
acquire the claim and retry — which on a terminal item is the one wrong
action, and a launched worker reading only the exit code read a completed
landing as a failed one.

`done` is reachable only through a completed close-out, so a refused
transition on an item that is already `done` with `merged_at` stamped and a
merge identity in its evidence record was refused because another close-out
finished first. The losing run reads those three facts fresh
(`standalone_item_merge_evidence.recorded_landing`) and, when all hold,
reports `result: landing_already_recorded` at exit 0, naming the session
the evidence record says wrote it and repeating no re-acquire hint. Every
other refusal is unchanged: an item short of `done` still has close-out
work, so a missing claim there remains the refusal it always was. The
evidence record carries `recorded_by_session_id` for this reason — the
transition ledger records no session, and the claim that would have named
one is exactly what the winner released.

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

### Why admission asks for the declared review stage

The merge boundary reads the item's current stage and lands from there.
Nothing in that reading consulted the stage the pinned workflow declares for
review, so an item still in implementation could have a pull request armed
and a queue entry created for work no review stage had seen, and the
close-out then asked for a jump straight to the terminal stage. Both halves
of that are now refused, and they are refused in two different places
because they are two different acts.

The status write refuses the jump itself: a forward move must be an edge the
pinned version declares, checked before the target stage materializes any QA
row or approval request in its name. That alone cannot protect the landing,
because `--skip-status` legitimately lands a branch without moving the item —
an item-bound deployment run needs the merge identity before close-out. So
admission asks the same declared question directly: has this item reached
the stage its own workflow declares for review, where review is the stage
the lane-activating stage's declared edge leads to. A definition that
declares no such stage — the floor workflow delivers straight from
implementation — is admitted unchanged.

Reaching that stage is what runs the review stage's own gates. Admission
never records that a review happened; it refuses to land work that has not
had one, and it fails closed when it cannot read the pinned definition,
because a boundary that cannot ask the question must not answer it with a
landing.

### Why re-entry asks by patch identity, not by sha

A lane rebased after its own landing points at commits that are copies: same
patches, fresh shas, and nothing an ancestry read can attribute to the merge
that already took them. Close-out asked only by sha, so it classified those
copies as new work — published the lane, opened a second pull request, and
recorded that number over the one that actually merged. The replacement pull
request had nothing to land, so it closed unmerged, and close-out then waited
permanently for merge-group CI evidence a pull request that never landed can
never produce. Its diff carried the second hazard: a lane on a base that old
proposes reverting everything merged since.

`git cherry` answers the question the sha reads cannot, comparing patch
identity rather than commit identity. So a head the base branch does not
contain is asked once more whether any commit it carries is missing from the
base, and a lane holding only copies converges on the landing already
recorded instead of arming a second one. The same read runs at both places
the old answer was wrong: close-out's own landing check, and the pull-request
lookup that decides whether the merged pull request is this lane's.

Two facts are required, not one. The base must contain the commit the merge
receipt recorded — that is the identity the convergence preserves, and
without it there is nothing to converge onto whatever the patches say. And
the lane must hold no commit whose patch the base lacks, which is what keeps
a retry after a red train and deliberate new work on the ordinary landing
route. A comparison that could not run answers "still has work", because
reading an unreadable checkout as "already landed" would close an item out
against a merge nobody confirmed.

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
- A standalone landing is refused while the item is still in implementation,
  including under `--skip-status`. The refusal names the declared review
  stage and the transition that reaches it.
- Closing an item out straight from implementation is refused by the status
  write itself. Rework, exceptional states, declared jumps, and a write that
  names its own source — the done transition, an advance skip route, an
  operator status repair — keep working unchanged.
- A close-out re-entered on a lane holding copies of already-merged commits
  converges on the recorded landing instead of publishing the lane and
  opening a second pull request. The recorded pull request number, merge
  commit, and touched files keep the identity the landing gave them.
- The lane candidate that is genuinely new work is unaffected: it is still
  refused with the fresh-work-item recovery, and an unmerged retry still
  lands through the ordinary route.
