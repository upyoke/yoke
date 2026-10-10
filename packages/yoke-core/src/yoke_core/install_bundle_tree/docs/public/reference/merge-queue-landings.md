# Merge queue landing notices

`yoke merge item PREFIX-N` verifies the exact candidate and arms its pull
request. A headless worker receives `landing_pending=true` and waits for the
control plane's landing notice. Re-enter the same merge command when that
notice arrives, retaining its result and verification evidence.

The existing landing observer reads the registered pull request during relay
upkeep. A recorded admission or a pending observation that GitHub armed or
queued that same pull request requires a full queue read even after GitHub
clears merge-when-ready. This distinguishes a stopped landing from a pull
request that was opened for verification and has never been armed. The durable
landing record supplies this fact; diagnostic events do not.
Before replacing that held observation, the observer retains its episode in
the existing item landing marker until the stopped notice reaches its holder.
This keeps a failed notice transport retryable on the next observation.

When GitHub holds neither arming nor a queue entry, the observer sends one
stopped-landing notice to the item's claim holder through the existing wake
route. Required checks that failed or were cancelled appear in the notice;
the stop is still reported if a later rerun passed without restoring arming.
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
