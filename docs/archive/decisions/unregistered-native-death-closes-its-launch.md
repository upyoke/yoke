# A native that dies before registering closes its launch on that poll

Decision recorded 2026-09-04.

Extends [`launch-named-process-death-needs-no-ttl.md`](launch-named-process-death-needs-no-ttl.md)
to the launches that never reached a session at all.

## Decision

The relay poll reports every launch it still supervises whose native process
is verifiably gone. A supervision record exists only until the launch's
instruction reaches a registered session, so a live record plus a dead process
names a launch whose worker never started.

The control plane closes such a launch immediately — `state="failed"`,
`result_code="native_exited_unregistered"`, `closure_reason=
"native_exited_before_registering"` — carrying the exit code, the capture
reference, and the last line the native said. A launch that did register a
session is skipped here and stays with the verified-death path, which has a
session to ask whether the worker ever worked. The ten-minute registration
deadline is untouched for a process that is still alive.

Every Cursor ACP launch now writes the same capture the supervised harnesses
write. The relay speaks ACP itself rather than spawning a supervisor, so the
turn's account existed only in memory: the child's stderr in a bounded drain,
and the turn's fate in a thread that discarded it inside a bare `except`. Both
now land in `nd-<launch-id>.capture` — the outcome in the stdout half, the
child's stderr in the stderr half — written once while the child is alive and
again once it has exited.

The closed launch is visible where the failed ones already are: its result
code joins the fleet report's unregistered-launch section, and
`yoke session-control launch get` renders its diagnostic reference through the
same fields every other native failure uses.

## Why

A deadline is a way of waiting out an ambiguity. The machine that started the
native has no ambiguity to wait out — it kept the pid and the start time, and
it watches the process. Spending ten minutes anyway leaves the launch reading
in-flight, the work reading staffed, and the operator with nothing to read.

The observed instance, 2026-09-04: four `cursor-cli` launches ran their first
turn, fired no hook, and each sat in `registration_pending` for the full ten
minutes before closing as `registration_deadline` with no captured output. The
ACP drain thread had terminated each process within seconds of its turn ending
and swallowed every exception on the way. The relay held the answer the whole
time and reported none of it.

## Why the record, rather than a new registry

Custody already answers "did this launch reach a session": the relay writes a
supervision record for every native it starts, and delivering the instruction
inside a registered session's own hook removes it. Reading that file needs no
second registry and no new state, and it is written identically on every
harness — which is why the rule is one rule rather than one per harness.

Authority still rests on the launch row, not the file. The relay reports; the
control plane checks the assigned machine, the authorized projects, the
absence of a registered session, and that the launch is still in flight before
it closes anything.

## Why the record is dropped once the report lands

The process the record names is gone, so containment has nothing left to
terminate with it, and re-reporting it every poll would repeat one fact
forever. A refused report keeps every record instead, so the next poll tries
again. The containment sweep's TTL remains the backstop for a record no report
ever cleared.

## Alternatives considered

**Shortening the registration deadline.** Rejected: the deadline serves a
native that is still coming up, and shortening it would fail those launches
early while still teaching nothing about the ones already dead.

**Reporting through the launch job's own terminal report.** Rejected: that
report is settled at spawn, and its lease is gone by the time the native dies.
The liveness poll already carries "what this machine proved is gone", and a
launch death is that same fact about a launch instead of a session.

**Giving Cursor a supervisor process like Claude and Codex.** Rejected as far
larger than the gap: the ACP transport must stay in the relay to speak the
protocol, and the two facts the capture needs are already in hand where the
turn ends.
