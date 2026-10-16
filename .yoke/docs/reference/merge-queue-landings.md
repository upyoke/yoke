# Merge queue landing notices

`yoke merge item PREFIX-N` verifies the exact candidate and arms its pull
request. A headless worker receives `landing_pending=true` and waits for the
control plane's landing notice. Re-enter the same merge command when that
notice arrives, retaining its result and verification evidence.

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
An `UNMERGEABLE` entry reports a conflict even while GitHub retains it behind
other entries: rebase onto the base and re-run verification before merge re-entry.
An unreadable queue membership proves no stop and is retried on the next
observation. A merged pull request receives the normal completion notice.

Recovery belongs to the holder: address the named check or protection rule
and re-run the same governed `yoke merge item` command. If the lane or base
moved, rebase onto the base, re-run verification, and re-enter that command.
The observer never re-arms a pull request. A governed retry recovers cancelled
or never-started required checks even when the open PR is already armed but
unadmitted; it never sends a duplicate arming request. It verifies current
head, newest workflow run and job evidence before one rerun POST. Active,
successful, superseded and enqueued attempts are protected. After three
cancelled attempts, inspect job annotations and fix the runner or workflow
limit before starting a fresh declared attempt. An accepted rerun is not a
pass: required checks must be replaced on the exact candidate. A new
`workflow_dispatch` is a fresh attempt whose head and replacement need proof. Repeated observation reuses the
same stop notice; a new governed arming starts a new episode.

## Re-landing an item that already landed

An item keeps its current landing until a new pull request actually merges.
When the merge boundary records a pull request for an item that already
landed (its `merged_at` or `merge_queue_landed_at` is set), the pull request
becomes a re-land attempt in
[`merge_queue_landing_attempts`](db-reference/merge-queue-landing-attempts.md)
and the item's `merge_queue_*` columns stay on the previous landing. One
attempt is open per item; a newer pull request closes the older attempt as
superseded.

The observer reads the open attempt instead of the delivered landing. When
the attempt merges, the observer moves the item's columns onto it, stamps
GitHub's merge time and sends the normal completion notice. When it closes
unmerged, the attempt closes with the reason `pull request N closed without
merging; the item keeps its previous landing`, the item's landing is
unchanged, and an armed attempt's holder gets the stopped-landing notice.
The board label, the fleet landing readback, `github.merge_queue.readiness`
and the waiting worker describe the open attempt. `yoke items detail get`
shows the current landing under `merge_queue` and the open or last closed
attempt, with its reason, under `merge_queue.attempt`.

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
