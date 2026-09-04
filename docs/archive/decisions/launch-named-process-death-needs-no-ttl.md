# A launch-named process death ends its session on the poll that saw it

Decision recorded 2026-09-04.

Refines the staleness precondition in
[`relay-verified-process-death.md`](relay-verified-process-death.md) and the
holdings boundary in
[`relay-process-death-respects-session-holdings.md`](relay-process-death-respects-session-holdings.md).

## Decision

When a relay reports a session whose process it proved gone, and the report
names the launch the machine started, the control plane no longer waits for
the session's staleness TTL to agree. It applies the report on the poll that
observed the exit.

The report then resolves one of two ways:

- **Nothing outstanding** — no work, coordination, path, or
  strategy-document holding; not parked; not awaiting an answer it asked the
  steering role for. The session ends with
  `end_reason="process_verified_dead"`, and its pending inbound envelopes are
  cancelled so their senders read `cancelled` rather than waiting on a
  delivery no process can take.
- **Something outstanding** — the row records `native_process_gone_at` plus
  the evidence, keeps every claim, and stays live for deliberate termination
  or the holdings TTL. The status names which of the three it was:
  `claims_held`, `parked`, or `awaiting_seat_reply`.

A report resting on a hook-written process anchor alone still waits for the
TTL. Only the launch handle is the machine's own custody record of a process
it started, and only that record carries the exit code and exit time the
supervisor observed.

## Why

The TTL exists because the control plane cannot tell a long-thinking agent
from a dead one. A launch-named report carries no such ambiguity: the machine
started the native, kept its pid and start time, and is reporting that the pid
is no longer that process. Waiting the TTL out anyway spends twenty minutes
proving something already proved.

The observed instance, 2026-09-04: a headless `codex exec` worker released its
claim at 14:06:27Z, sent its terminal report, and its process exited after its
final Stop at 14:07:39Z. The Stop-time `end_session_if_empty` skipped, because
a notice injected at 14:07:14Z was still inside the wake-acknowledgement
grace, and nothing re-ran the end afterwards — Codex wires no `SessionEnd`
hook. The relay had the exit in hand within a poll. The row nonetheless sat
open until a person terminated it by hand at 14:30Z. Every other worker that
day ended cleanly only because no message happened to land in its last
minutes.

## Why parked and an open question hold the row

Both are states the session declared about itself, and neither is settled by
the process being gone.

A parked session is resumable state: it stamped a wait it expects to be
brought out of, and a resume spawns a fresh native. Ending the row on the
exit would discard the wait rather than serve it.

A session that asked the steering role something and has no answer yet is
owed one. Ending it drops the question along with the row that carries it.
The predicate is deliberately narrow — it reads the session's own
role-addressed messages through `message_asks`, so a terminal report, which
asks for nothing, is not a wait. That narrowness is the whole point: a
worker's last act is overwhelmingly a report, and counting reports as waits
would keep every finished worker alive forever, which is the failure this
decision exists to remove.

## Why the senders are told

An envelope pending against a session whose process is gone will never be
delivered by that process. Leaving it pending leaves its sender waiting on an
answer that cannot arrive. Cancelling it is the same silencing deliberate
termination already performs, through the same helper, with
`process_verified_dead` naming which absence closed it.

The operator decision behind this: a pending message does not keep an exited
worker alive. An undeliverable message fails loudly to its sender instead.

## Alternatives considered

**Gating the Stop hook on acknowledgement.** Rejected: an acknowledgement
outage would loop, and the hook cannot observe its own process exiting
anyway.

**A new hook event for process exit.** Rejected: the relay is already the
native's parent and already reports liveness each poll. A second channel for
a fact the first one carries adds a surface without adding evidence.

**Dropping the TTL for every proven-dead report, anchor-sourced included.**
Rejected for now. An anchor is written by whatever hook ran, for whatever
session; the launch handle is the machine's record of a process it started
itself. Keeping the TTL where the custody is weaker costs nothing, because
the population that motivated this decision is launched workers.
