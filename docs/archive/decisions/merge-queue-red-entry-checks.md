# Red required checks on a merge-queue landing are terminal

## The gap

Queue landing armed merge-when-ready and then polled for up to 45 minutes.
When the pull request's own required checks had already concluded red
with nothing in flight, GitHub would never enqueue the pull request. The
poll still spent its budget and returned a resumable timeout, which
reports a terminal verdict as pending.

## The decision

On every landing poll, read the pull request head's checks. When any
have concluded `failure` / `error` / `cancelled` / `timed_out` /
`startup_failure` and none are still in flight, return a **terminal**
red verdict immediately (exit 1), naming the checks, pull request, head
sha, and recovery (`fix on the lane, commit, re-run yoke merge item`).

The poll-budget timeout remains only for genuinely pending states
(checks queued or in progress, queue entry building, `merge_group` run
in flight).

**Disarm merge-when-ready** on that red path. Leaving it armed would let
a later green on the same pull request auto-merge without this gate
recording a verdict. Re-running `yoke merge item` after a fix re-arms
as before. If disarm itself fails, the refusal names that failure and
the recovery to disable auto-merge on the pull request before pushing.
