# The machine reports a session whose native process it can prove is gone

Decision recorded 2026-08-27.

The holdings boundary was refined by
[`relay-process-death-respects-session-holdings.md`](relay-process-death-respects-session-holdings.md).

## Decision

Each poll cycle, a machine's relay scans its own session process records
and reports to the control plane every session whose recorded pid is no
longer the recorded process. The control plane applies a report only when
the session belongs to the reporting machine, sits in a project that relay
is authorized for, and is already past the short stale TTL. It ends an empty
session through `end_session` with `end_reason="process_verified_dead"`.
A session with any current holding returns `claims_held`, records the
observation, and stays live.

A session with no local record at all proves nothing and is never
reported. The stale-session cleanup sweep remains the backstop for
everything this path cannot demonstrate.

## Why

A session row reads `active` until its heartbeat ages past the stale TTL,
then `stale` until the cleanup sweep reaches it. For a native that
actually died, both readings are wrong in a way that costs real work:

- `stale` maps to the `message_idle` wake operation, which injects into a
  live process. There is no process, so every wake for that session fails
  and re-fails until the sweep's much longer holdings TTL expires.
- The row can keep holding work while no native process can answer a wake,
  so the fleet needs an explicit operator-facing observation.

The observed instance: a cursor worker process died at 12:46Z and its row
stayed running, holding claims, for hours.

The control plane cannot distinguish a long-thinking agent from a dead one
— quiet looks identical either way, which is exactly why the TTL exists.
The machine that started the native does not have to guess. It already
kept the pid, in records written for other reasons, and comparing that pid
against the live process table is cheap. For an empty ghost, ending the row
makes a later wake a fresh native resume. For a holder, recording the fact
without releasing authority lets the operator terminate deliberately or
lets the holdings TTL settle abandonment.

## The evidence rule

Two record families name a session's process, both already written:

- the launch handle (`session-native-handles/<launch-id>.json`) the relay
  retains when a launched native registers, so termination can still reach
  a process that containment has released;
- the process-anchor registry (`session-anchors/<anchor-pid>.json`) the
  hooks write for ambient identity.

A record testifies only against itself: the recorded pid must still be the
recorded process, compared by start time so a reused pid reads as gone
rather than as alive. A session is reported only when it has at least one
record and every one of them is dead. An anchor marked
`shared_by_multiple_sessions` is skipped — a pid that cannot name one
session cannot testify about one session's death either.

## Local records follow the control-plane outcome

A record whose process is gone is spent only when the control plane ends the
session, so only IDs returned in `ended` have their records pruned. A
`claims_held` response retains the records and is re-reported; after claims
are released, a later report can end the empty ghost. A refused report also
prunes nothing, so a server that starts serving this function later still
hears about every death observed while it could not.

## Why the report is not authority

The relay says what it observed; the control plane decides. Machine
ownership, project authorization, stale TTL, and the complete shared
holdings projection all run server-side. A relay cannot end a session it
does not run, one in a project it does not serve, one touched since the
process died, or one that still holds authority. A session that fails any
check comes back with a named status rather than silence, because a silent
no-op here is indistinguishable from the ghost this path exists to remove.

## Rollout

`session_control.relay.liveness` is a new registered function. A relay
running ahead of its control plane gets the typed `function_version_skew`
answer, logs it, and keeps polling: the sweep degrades to the TTL behavior
that existed before this path, and nothing else in the cycle is affected.

## Alternatives considered

**Extending the relay claim payload instead of adding a function.** The
claim request forbids extra fields, so a newer relay's claim would be
refused outright by an older server — the poll loop itself would stop,
which is a far worse failure than a skipped liveness sweep.

**Having the server tell the relay which sessions to check.** The relay
does not need to be told: the records are its own, and reporting from a
local scan keeps the whole exchange to one dispatch that happens only when
there is something to report.

## Related

A dead process is the easy half. The same relay poll also handles a session
that is unmistakably alive and will still never speak again, because the
model provider ended its turn:
[`codex-error-terminal-turn-wake.md`](codex-error-terminal-turn-wake.md)
covers reading that from the session's own turn record, and
[`vendor-stopped-session-resume.md`](vendor-stopped-session-resume.md)
covers what the relay then does about it.
