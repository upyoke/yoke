# Sessions

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > Sessions
<!-- /yoke:breadcrumbs -->

Inspect session liveness, work ownership and steering communication.

## Sessions

Workbench **Sessions** lists harness sessions against this universe: who is
running, what item they hold, mode (dash, conduct, wait, …).

Held item IDs show Frozen and Blocked pills from the item's own state. If
both apply, Frozen appears first and colors the active workflow segment ice
blue; Blocked remains visible beside it. Blocked alone colors that segment
red. Completed and upcoming segments retain their normal colors. A parked or
idle session does not, by itself, mark its item Frozen or Blocked.

Every session has one liveness: `active`, `waiting`, `stale`, or `ended`. A
parked session that still holds a work claim is `waiting` — quiet on purpose
for a deploy, a landing, or a migration slot, and resumed by the next message
(from its transcript when its process has exited) — and is never reported
`stale`, however long it has been quiet. `stale` is a quiet session nothing
accounts for. The Sessions page, the Frontier, and `yoke sessions list` all
read this one classification.

The roster opens on **Active**, which includes active, waiting, and stale
sessions. Stale sessions remain visible as light-red cards with a red `stale`
pill. **All** includes ended sessions too, while **Ended** shows only
ended sessions. **Reclaim stale** counts only the sessions the reclaim sweep
would act on — quiet past their TTL and holding no work claim — and reloads
the roster after cleanup, so reclaimed rows leave Active immediately.

On the **Frontier**, every claimed item's card carries its holding session's
chip — surface, park state, and quiet reason — whichever band it lands in.
**Owner unavailable**, with its advice to release the claim or terminate the
session, appears only for an abandoned holder: not parked, its process gone,
and quiet past its activity window.

Every session card offers **Message**, including ended sessions. An idle or
parked session whose wake belongs to the operator shows **Queued — delivered
when you wake this session.** Its next hook delivers the message after you
open the chat and start a turn. A missing relay leaves messaging available;
the card explains that hook delivery can proceed and automatic wake waits
for the relay to reconnect. Active sessions keep their normal hook delivery.

Native wake routes that refuse delivery spend a bounded retry budget. Exhaustion
sends the named failure and recovery to the original sender and the covering
steering seat; read `yoke messages get MESSAGE-ID` for the receipt and attempts.
Operator-driven hook delivery keeps its own wait without spending that budget.
Detached turns keep their capture current while waiting on a command. If the
relay contains a native, verified custody death reopens pending wakes held by
that exact process and retires Fleet's old `native_turn_running` label.

Sessions own work claims. Implementation lanes require an active claim and a
registered worktree. A persisted active work claim keeps its session live
through stale, idle, parked, process-gone, and startup sweeps. This includes
release waits; parking records the delivery wait for wake routing and does
not determine retention. Claim release, completion, cancellation, and
authorized operator termination free ownership. Any session holding a live
steering seat on any project may terminate a session on any project, and
termination releases every claim the target holds, steering seats and their
paired document locks included. Logical termination cancels
messages immediately and queues one physical reap. The relay retains
identity-bound process/group custody until verified exit: TERM has a 2-second
grace, followed by KILL and a bounded 2-second exit check. Missing custody,
signal denial, and unverified exit remain unresolved. Inspect machine custody
and permissions, then explicitly repeat `yoke sessions terminate SESSION-ID
--reason R` to retry a failed reap; prior failed evidence is retained in the
existing reap record. A pending attempt is not duplicated and a verified
success stays a no-op. Claude's native job stop has a separate 20-second
command timeout. Registration transfers custody only after adoption succeeds;
a failed adoption keeps the registered native protected in supervision. Explicit session end releases
the claims it still holds. A claim conflict names its holder and requires one
of those explicit actions rather than a heartbeat timeout.

An active steering scope appears on the generated board with its holder,
project and held strategy documents, claim age, liveness, steering-launched
worker count, and unacknowledged report count. In Workbench, Steering badges
show the same scope, steering-launched workers group under their holder, and
each of those workers shows whether its latest deliberate report was sent or
acknowledged. Every worker reaches the seat deliberately with `yoke say
--steering`; ending a turn sends no Fleet message. Workers reserve those
messages for something the seat must act on — a failure, blocker, conflict,
decision, question, or terminal outcome — and keep progress in their own
visible output. A substantive peer request addresses its intended worker with
`--item` (or an exact listed `--session` when no claim addresses the recipient)
and copies the relevant seat by adding `--steering`; those anchors union. The
recipient replies to the original requesting session and also copies steering,
particularly to accept or refuse, report a scope conflict or blocker, or ask
for a decision. A rejection sent only to steering leaves the requester
uninformed. When the sender holds no applicable item, it supplies the explicit
scope with `--steering-scope '{"project_id": N}'`. Session IDs are always copied
whole from a listing, never guessed or reconstructed. Acknowledgement records
receipt, not acceptance or implementation. A report addressed to the role has
a recipient whether or not a seat is live, so sending, previewing, reading, and listing one all report
that recipient's own state: `awaiting_seat` with the scope it is queued for,
`delivered` naming the seat holding it, or `acknowledged`. A queued report is
therefore never a message that went nowhere. The next seat covering the
sender's item takes queued reports when it is acquired, and the fleet report's
awaiting-seat count reads the same coverage. A document seat covers every item
linked to its document, so it takes and counts those items' reports even when
another project owns the item. These views derive from existing
claims, document locks, launch provenance, and message-recipient receipts;
they do not create separate state.

Ambient session identity comes from the harness (env / process anchor /
conversation mapping) — operators should not invent session IDs.

`yoke sessions hook-overhead [--hours N]` summarizes hourly PreToolUse and
PostToolUse client wall time, evaluator time, and their remainder, then shows
completed tool-call latency beside timed/total coverage globally and per
harness. Tool latency re-reads repaired `session_tool_calls` owner timestamps;
a start or client wall still inside the pending-delivery window is pending,
not incomplete. Missing durations outside that window stay unknown rather
than becoming zero. The `--hours` observation cutoff and the pending window
are explicit on the JSON result. The distinct-session `ACTIVE*` count is a
fixed-hour activity proxy, not the live roster or proof of simultaneous
execution. Add `--json` for the registered result envelope.

`yoke hook benchmark --samples 5 [--json]` runs the harmless system `true`
command between normal PreToolUse and PostToolUse checks. It records direct
pre/command/post/envelope wall times and reads evaluator/client-wall phases
from durable `HookDispatchTelemetry`, with exact timing coverage, harness,
surface, revisions when available, time window, run count, and separately
defined live-roster and running-session proxy counts. A phase still in
flight is pending delivery, not incomplete coverage. Save a JSON report and
compare it with `--compare REPORT.json`; mismatched identity, revisions,
command, or sample count, pending delivery, and incomplete
evaluator/client-wall coverage, are labelled incomparable.


## Related

- [Items](../items/index.md)
- [Inbox and messaging](inbox.md)

<!-- yoke:contents -->
- [Inbox and messaging](inbox.md) — Read decisions and send messages to their intended recipients.
- [Steering report](steering-report.md) — Inspect available work, holders and session delivery failures.
- [Steering report delivery](steering-report-delivery.md) — Read deployment waits, shared capacity and report deltas.
- [Fleet policy](fleet-policy.md) — Read session launch limits and supervision policy.
- [Path claim model](model/path-claims.md) — Read claim ownership, path coverage and overlap decisions.
- [Linux relay](linux-relay.md) — Install and inspect login-scoped Linux relay supervision.
- [Session model](model/sessions.md) — Read harness identity, liveness and work-claim ownership.
- [Shared coordination model](model/coordination.md) — Read shared-operation leases, host queues and session accounting.
<!-- /yoke:contents -->
