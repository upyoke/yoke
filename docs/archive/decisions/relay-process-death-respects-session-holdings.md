# Process-death evidence does not revoke session holdings

Decision recorded 2026-09-03.

## Decision

A relay report proving that a session's recorded native process is gone is
process evidence, not authority to release control-plane holdings. The
control plane ends a reported session only when it holds nothing. If it has
any current work, steering, coordination, path, or strategy-document
holding, the report returns `claims_held`, leaves the session and every
holding open, and stores the process-gone observation.

[`launch-named-process-death-needs-no-ttl.md`](launch-named-process-death-needs-no-ttl.md)
later added two more states that hold the row the same way — parked, and
awaiting an answer the session asked the steering role for — and dropped the
staleness precondition for a report naming the launch the machine started.

Only deliberate termination or the ordinary stale-session holdings TTL may
end that spared session. The stale-alive status probe likewise gathers
evidence and may trigger wake delivery, but it never ends a claim holder.

## Why

A recycled desktop or IDE process is not proof that the conversation, its
session identity, or its work was abandoned. Ending the session on process
death released live claims even though the conversation could continue in a
replacement process. The machine had established one fact accurately and
the control plane drew a stronger conclusion than that fact supported.

The asymmetry is intentional: ending an empty ghost is reversible recovery;
releasing a live holder's authority can admit conflicting work.

## One holdings authority

The liveness handler reads
`sessions_holdings_projection.session_holdings_by_session`, the same complete
current-holdings projection used by session cards and fleet reporting. It
does not maintain a second query for a subset of claim kinds. A non-empty
`current` list is the whole preservation decision, independent of harness,
surface, launch origin, or holding kind.

## Observation lifetime and operator wording

`harness_sessions.native_process_gone_at` and
`native_process_gone_evidence` retain the relay observation. A strictly later
heartbeat, tool call, or episode start supersedes it, proving that a process
has resumed the session. Until then, the session roster and fleet report say
*process gone, claims held — terminate deliberately if dead*, and no wake
recipe is offered for a process known not to exist.

**The stamp names the death, not the poll.** Retaining the local record is
what makes a later report possible, and it also means the same dead record is
reported on every poll for as long as the holdings keep the row open. Stamping
each of those reports with its arrival time made one old exit permanently
newer than every later resume: a session whose first native exited cleanly,
which was then woken and worked for another ninety minutes, still read as a
fresh death because the newest report was minutes old.

So which death the row describes is decided before anything is written, by
comparing the reported process — its pids and their start times — against
what the row already carries.

A report about the process already recorded is the same death said again.
Its own exit time, once the machine has read one from the launch's diagnostic
capture, *corrects* the stamp an earlier report had to guess from its own
arrival; with no exit time it keeps the time that first report earned. The
correction moves the stamp earlier on purpose: without it an inflated polling
stamp outlives the very evidence that could repair it.

A report about a different process is a different death, and the row
describes one. The later death is the one that matters, so a report whose
death predates what the row already carries is dropped whole — stamp and
evidence together. Dropping only the stamp is the trap: a delayed report of
an older native's clean exit would keep the newer timestamp while replacing
the crash evidence under it, and a declared wait would then read the row as
accounted for while the real failure went unnamed.

**A declared wait accounts for a normal exit.** A headless worker's native
exits when its turn ends, so a session that armed a merge-queue landing and
stopped, or parked itself waiting on an answer or a dependency, has a dead
process and nothing wrong with it. Where the machine measured `exit_code` 0
and the session declares such a wait — `mode='parked'`, or holding an item
armed in the queue and not yet landed — the derived observation is dropped and
the card shows that wait with its own reason. This is a projection judgment,
not masking: the evidence stays stored and truthful. The landing half rides
`claimed_item_facts` as `item_awaiting_landing`, the one batched read that
already loads every claimed item's row for both surfaces, so neither pays a
second query to learn it. A non-zero exit and an
exit nobody measured are never accounted for, whatever wait is declared,
because a park is not a place to hide a crash.

**A session the machine still runs a native for is not reported at all.**
The report reads the launch-handle and process-anchor families, and a launch
handle survives its native, so a session that was later resumed carried a
spent handle beside a live resume-custody record. The dead-session scan now
also asks the resume-custody reader whether this machine is still running a
native for that session, and skips it when it is — the same custody question
a wake asks before starting a second native, in the one place the machine
already knows the answer. What "still running" means is settled by
[`defunct-process-is-an-exited-process.md`](defunct-process-is-an-exited-process.md).

## Local record lifetime

The relay prunes only the local process records for session IDs the control
plane actually ended. Records for a `claims_held` response stay in place, so
after the holdings are released a later report can end the now-claimless
ghost. A refused report continues to retain records as before.

## Relationship to the original decision

[`relay-verified-process-death.md`](relay-verified-process-death.md) established
the evidence-bound machine-reporting protocol. This decision narrows the
server action and record-pruning boundary while retaining that protocol.
