# Sessions

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > Sessions
<!-- /yoke:breadcrumbs -->

Inspect session liveness, work ownership and steering communication.

## Sessions

Workbench **Sessions** lists harness sessions against this universe: who is
running, what item they hold, and whether each is parked.

Held item IDs show Frozen and Blocked pills from the item's own state. If
both apply, Frozen appears first and colors the active workflow segment ice
blue; Blocked remains visible beside it. Blocked alone colors that segment
red. Completed and upcoming segments retain their normal colors. A parked or
idle session does not, by itself, mark its item Frozen or Blocked.

Every session has one liveness: `active`, `waiting`, `stale`, or `ended`.
`stale` means eligible for automatic reclaim, with every work-claim,
document-holdings, in-flight and episode-progress rule applied. A live active
work-claim holder never reads stale. An intentional pause declared by mode
`parked` or turn posture `waiting` while holding work is `waiting`, displayed
as **parked**, however old its activity becomes. Other protected live sessions
remain active; their activity age is a separate diagnostic. Silence does not
declare a pause. Ended sessions stay ended.

The roster opens on **Active**, including active, waiting and stale sessions.
**All** includes ended sessions; **Ended** shows only ended sessions.
**Reclaim stale** counts exactly the stale sessions in the same scope and
snapshot. Execution rechecks the shared eligibility decision and reports
newly protected sessions skipped, with their reason; refresh the roster before
retrying. Explicit authorized termination is a separate action and can settle
protected claims. Cleanup reloads the roster so reclaimed rows leave Active.

On the **Frontier**, every claimed item's card carries its holding session's
chip — surface, park state, and quiet reason — whichever band it lands in.
**Owner unavailable**, with its advice to release the claim or terminate the
session, appears for a holder without a declared pause whose process is gone
and whose surface cannot resume it from its transcript.

Every session card offers **Message**, including ended sessions. An idle or
parked session whose wake belongs to the operator shows **Queued — delivered
when you wake this session.** Its next hook delivers the message after you
open the chat and start a turn. A missing relay leaves messaging available;
the card explains that hook delivery can proceed and automatic wake waits
for the relay to reconnect. Active sessions keep their normal hook delivery.

Native wake routes that refuse delivery spend a bounded retry budget. Exhaustion
sends the named failure and recovery to the covering steering seat. The
original sender is not notified; the message state is their record. Read
`yoke messages get MESSAGE-ID` for the receipt and attempts.
Operator-driven hook delivery keeps its own wait without spending that budget.
A relay wake whose lease expires before the relay reports anything spends
nothing either, so an explicit wake survives a relay outage: the peer-hook
broker gets the first retry, then the relay claims it again. After three such
expiries the receipt keeps the charge and records the `relay_lease_expired`
escalation; Fleet shows it as `last attempt failed (relay_lease_expired)`.
Recover with `yoke session-control session wake SESSION-ID` once the relay
reports again.

An explicit `yoke session-control session wake SESSION-ID` returns its queued
receipt after about one second if no relay or broker claims it. A claimed
attempt can wait up to ten seconds total for its result. A queued or unfinished
receipt includes `yoke messages get MESSAGE-ID` to inspect later delivery.
Detached turns keep their capture current while waiting on a command. If the
relay contains a native, verified custody death reopens pending wakes held by
that exact process and retires Fleet's old `native_turn_running` label.

The relay releases an unstarted job when stopping or when all settlement
workers are busy. Its report records `relay_stopping` or `relay_workers_busy`;
the job becomes eligible for the next poll without waiting for lease expiry.
A failed release report stays in the machine's pending reports and retries
before new claims. Launch closure evidence calls claim time
`attempt_claimed_at`; `native_started_at` records an observed native spawn.

Sessions own work claims. Implementation lanes require an active claim and a
registered worktree. A persisted active work claim keeps its session live
through stale, idle, parked, process-gone, and startup sweeps. This includes
release waits. Parking records delivery wake routing; claims own retention.
Before parking on another item, [record its dependency](../agents/rules/delivery.md#wait-on-another-items-merge-or-delivery). Claim release, completion, cancellation, and
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
sender's item takes queued reports when it is acquired: each gets that seat's
ordinary session receipt and injects through the same hook as a live send, and
acquire prints each message id with its acknowledge command. The fleet report's
awaiting-seat count reads the same coverage. A document seat covers every item
linked to its document, so it takes and counts those items' reports even when
another project owns the item. These views derive from existing
claims, document locks, launch provenance, and message-recipient receipts;
they do not create separate state.

A session belongs to the project whose registered folder it started in, else to
its organization (shown as **Outside any project**), and keeps that scope. Its ID
comes from the harness; never invent one. A session may claim items in any project
it can access ([session scope](../agents/rules/lanes-and-claims.md#session-scope)).

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
