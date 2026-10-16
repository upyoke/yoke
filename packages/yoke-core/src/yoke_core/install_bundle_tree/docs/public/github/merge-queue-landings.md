# Merge queue landing notices

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [GitHub](index.md) > Merge queue landings
<!-- /yoke:breadcrumbs -->

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
The observer never re-arms a pull request. Repeated observation reuses the
same stop notice; a new governed arming starts a new episode.

The harness manifest determines whether the existing wake route can resume
the holder automatically. Operator-driven surfaces need the operator to
re-enter the session. If the holder is gone, the notice routes to the project's
steering seat for restaffing.

Before recording a landing, the merge boundary fetches the remote default
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
