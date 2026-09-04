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
*process gone, claims held — terminate deliberately if dead*. A process-gone
holder is actionable even when parked or below the ordinary idle threshold,
and no wake recipe is offered for a process known not to exist.

## Local record lifetime

The relay prunes only the local process records for session IDs the control
plane actually ended. Records for a `claims_held` response stay in place, so
after the holdings are released a later report can end the now-claimless
ghost. A refused report continues to retain records as before.

## Relationship to the original decision

[`relay-verified-process-death.md`](relay-verified-process-death.md) established
the evidence-bound machine-reporting protocol. This decision narrows the
server action and record-pruning boundary while retaining that protocol.
