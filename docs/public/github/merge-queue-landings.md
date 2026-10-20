# Merge queue landing notices

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [GitHub](index.md) > Merge queue landings
<!-- /yoke:breadcrumbs -->

`yoke merge item PREFIX-N` verifies the exact candidate and arms its pull
request. A headless worker receives `landing_pending=true` and waits for the
control plane's landing notice. Re-enter the same merge command when that
notice arrives, retaining its result and verification evidence.

Before it selects a route, the command asks the item's integration dependency
gate (`merge.preflight.dependency_gate`). Queue admission only sees
predecessors that are queue members, so this gate is what keeps an item from
enqueuing while a predecessor is still being implemented. A blocked gate
refuses with `integration_dependency_blocked`, naming each predecessor and its
status; nothing is armed or enqueued. Wait for the predecessor's landing
notice, then re-run the same command. A gate that cannot be read refuses with
`integration_dependency_gate_unavailable` rather than landing.

The existing landing observer reads the registered pull request during relay
upkeep. A waiting worker's `merge_queue.landing.observe` call returns the
stored landing record without reading GitHub while that record is newer than
two refresh intervals. When no relay sweep has kept it current, for example on
a single-machine install with no relay running, the call refreshes the project
from GitHub itself, so a merge is reported within about two refresh intervals. A recorded admission or a pending observation that GitHub armed or
queued that same pull request requires a full queue read even after GitHub
clears merge-when-ready. This distinguishes a stopped landing from a pull
request that was opened for verification and has never been armed. The durable
landing record supplies this fact; diagnostic events do not.
Before replacing that held observation, the observer retains its episode in
the existing item landing marker until the stopped notice reaches its holder.
This keeps a failed notice transport retryable on the next observation.

When GitHub holds neither arming nor a viable queue entry, or the entry state
is `UNMERGEABLE`, the observer sends one stopped-landing notice to the item's claim holder through the existing wake
route. Required checks that failed or were cancelled appear in the notice;
the stop is still reported if a later rerun passed without restoring arming.
`mergeable=CONFLICTING` means the PR conflicts with the base: rebase onto the
base, re-run verification and re-enter `yoke merge item`. An `UNMERGEABLE`
queue entry with `mergeable=MERGEABLE` can conflict only with the train ahead.
The landing record snapshots the preceding PR numbers and shared changed
files. Wait for those entries to land or leave; then re-read `mergeable`:
`CONFLICTING` requires a rebase and verification, while `MERGEABLE` permits
re-enqueueing the unchanged head. Shared files explain possible overlap; they
do not prove a content conflict.
An unreadable queue membership proves no stop and is retried on the next
observation. So does an open pull request whose merge state GitHub reports as
unknown: GitHub reports that while it recomputes, including mid-merge after it
clears the queue entry and merge-when-ready, so the observation stays pending
until a later read shows the merge or a known refusal. A merged pull request receives the normal completion notice.

Recovery belongs to the holder: address the named check or protection rule
and re-run the same governed `yoke merge item` command. If the lane or base
moved, rebase onto the base, re-run verification, and re-enter that command.
For a snapshotted queue conflict, the observer waits for the entries ahead to
leave, rechecks base mergeability and required checks, and requests
merge-when-ready again on the unchanged head if it remains mergeable.
`yoke merge item --wait` consumes that recovery through the same server
record; it returns control to the lane holder when a rebase is needed.
An unreadable queue or file listing names the failed read and its repair;
no re-enqueue is sent without the needed evidence. Other stopped landings
require the holder's governed retry. A governed retry recovers cancelled
or never-started required checks even when the open PR is already armed but
unadmitted; it never sends a duplicate arming request. It verifies current
head, newest workflow run and job evidence before one rerun POST. Active,
successful, superseded and enqueued attempts are protected. After three
cancelled attempts, inspect job annotations and fix the runner or workflow
limit before starting a fresh declared attempt. An accepted rerun is not a
pass: required checks must be replaced on the exact candidate. A new
`workflow_dispatch` is a fresh attempt whose head and replacement need proof. Repeated observation reuses the
same stop notice; a new governed arming starts a new episode.

## Failed merge trains

After inspecting the failed run, a worker may claim one retry when the change cannot
explain the test failure. First message `yoke say --steering` with the test and CI run URL,
then re-run the same complete `yoke merge item` command with
`--retry-flake 'TEST: why the change cannot explain the failure'`.
The item records its pull request, head/base, run URL, reason and session before arming.
A second claim on that input pair refuses with `merge_train_flake_retry_exhausted`;
a second failure belongs to the item and requires a fix. The observer never claims a
flake automatically. A reservation is spent even if admission fails or its reply is lost;
inspect **Merge train retries** before recovery. See the
[verification policy](../agents/rules/verification.md#unexplained-test-failure).
An older serving build refuses this reservation with its serving floor; ask the
control-plane operator for a serving release that carries the function. Ordinary merges
remain available without this optional retry.

Automatic conflict re-entry requests Contents: write and Pull requests: write on its
installation token. If GitHub refuses access, restore those App permissions and token
scopes, then retry the governed merge. Each accepted automatic request is saved in the
item's **Queue re-entry receipts** section, including the pull request, head and acceptance
time; read it with `yoke items section get PREFIX-N --section 'Queue re-entry receipts'`.
Post-release proof requires a real receipt accepted after that release; unit tests alone
cannot establish it.

## Re-landing an item that already landed

An item keeps its current landing until a new pull request actually merges.
When the merge boundary records a pull request for an item that already
landed (its `merged_at` or `merge_queue_landed_at` is set), the pull request
becomes a re-land attempt in
[`merge_queue_landing_attempts`](../functions/merge-queue-landing-attempts.md)
and the item's `merge_queue_*` columns stay on the previous landing. One
attempt is open per item; a newer pull request closes the older attempt as
superseded. Opening a never-armed attempt preserves the prior landed
observation; closing that attempt unmerged leaves it available. Arming a new
attempt starts a new observation episode. Leaving the queue clears the
attempt's `enqueued_at`; the durable recovery record keeps the queue blocker
and shared files. Release enrollment and containment refuse a current run
member's open attempt with `item_landing_open`, naming its PR. Wait for the
correction to merge or close, then refresh the candidate and retry release
admission; the older landing cannot stand in for a correction still in flight.
A member removed with `yoke deployment-runs remove-item` no longer blocks the
run: its open correction rides a later release.

When a lane adds no content to its target, re-run `yoke merge item PREFIX-N`
with `--result` and `--verification`. Close-out verifies the newest completed
Merge Receipt against the fetched target and uses the pull request that
carried that merge. A newer merge carrying the lane candidate still uses its
own landing observation instead of an older receipt. A later open, unarmed pull request needs no landing
observation and is not armed again. `merge_recorded_landing_missing` means
no completed identity can be read: preserve the lane and ask the control-plane
operator to restore its recorded landing, then retry. An ancestry or carrier
read refusal names the checkout or provider access to repair.

The observer reads the open attempt instead of the delivered landing. When
the attempt merges, the observer moves the item's columns onto it, stamps
GitHub's merge time and sends the normal completion notice. When it closes
unmerged, the attempt closes with the reason `pull request N closed without
merging; the item keeps its previous landing`, the item's landing is
unchanged. An armed attempt first sends its holder the stopped-landing notice
and closes once that notice is delivered, so a failed notice is retried.
The board label, the fleet landing readback, `github.merge_queue.readiness`,
`github.merge_queue.hold` and the waiting worker describe the open attempt, so
holding a re-land holds and confirms its own pull request. An armed open
attempt also counts as the holder's landing wait: the turn-end Stop gate lets
the holder stop without a continuation or steering alarm, and the session
roster and fleet idle-holder check treat it as awaiting landing. An attempt
that is open but not armed, or closed, leaves the earlier landing in charge,
so the holder still owes close-out. Close-out records
the landing under the pull request it went through, not the delivered one.
`yoke items detail get` shows the current landing under `merge_queue` and the
open or last closed attempt, with its reason, under `merge_queue.attempt`.

The harness manifest determines whether the existing wake route can resume
the holder automatically. Operator-driven surfaces need the operator to
re-enter the session. If the holder is gone, the notice routes to the project's
steering seat for restaffing.

The observer saves the current PR's head branch, target, head SHA and merge
SHA in the item's existing Merge Receipts document in the same transaction as
its landing stamps, before sending the completion notice. Missing identity
leaves the landing unstamped and records `merge_landing_identity_missing` in
the project refresh error; retry with a complete GitHub PR readback. Release
containment can use this identity while worker closeout is still pending.
The worker still records results and verification and enriches that exact
receipt with changed files and contributed commits. Re-observation is
idempotent; a later landing preserves the earlier receipt's identity.

During worker closeout, the merge boundary fetches the remote default
branch and requires it to contain the exact candidate commit. The recorded
merge SHA is the merge on that fetched branch's first-parent history that
first carried the candidate: the item's own pull request merge. A merge-queue
batch's merge commit is the train's tip, so in a multi-PR batch it names the
last member's merge and never stands in for another member's landing. A later
target push cannot become the item's landing either. Local merges record the merge that first carried the candidate, or
the candidate itself for a fast forward. A failed fetch or missing candidate
returns a named refusal, retains the lane, and leaves the item before landing.
Repair routing or remote access and re-enter the same governed merge command.
A project with no remote proves candidate ancestry on its local default branch.

## Epic lanes

In a project that declares the merge queue, `merge-worktree` lands each epic
lane through the same queue route as `yoke merge item`, recorded on the epic
item. The queue retests the lane against the base branch when its train
forms, so items landing during the lane's checks cannot make it stale. After
the first lane lands, each later lane's pull request is a re-land attempt
(see above). A headless worker gets `landing_pending` with exit 9: the lane is
armed, not landed. When the landing notice arrives, re-run the same
`yoke watch merge merge-worktree` command to record the queue close-out, the
lane landing and lane cleanup. A failing capability probe refuses with
`merge_queue_probe_failed` rather than merging directly. Projects without the
queue keep the direct pull-request merge, which refuses `MergeTargetStale` when
the base moved during CI.

When an item has several active lanes, `yoke merge item` takes as its source
the lane whose head is the landing record's pull-request head. It verifies QA
at that commit, reruns parent-level Command cases in that lane, and keys the
merge receipt on that lane's branch. With no lane at that head it takes the
sole integration lane; otherwise it refuses, lists the lanes, and names the
recovery.

## Integration-lane merge refusals

Integration-lane merges record the verified candidate's first carrying merge
through `item_landings.record` before removing the lane. Local fast-forwards
record the candidate itself. The same transaction releases the epic's path
claims and migration territory; delivery still retains the work claim.

A Git integration or commit-hook failure reports `merge_integration_refused`
with Git's diagnostic and leaves the pending integration in its lane. Fix the
named refusal, complete the pending merge commit when one exists, then retry
the same merge command. An authored-file limit refusal therefore names the
file that needs splitting instead of classifying engine-created changes as
user dirt.
