# A native turn record reclassifies a session no wake route can reach

## The silent cell

The wake router picks its operation from two facts on the session row:
`turn_posture` and liveness. `waiting` selects the stopped-session native
resume; otherwise liveness selects `message_active` (active),
`message_idle` (stale), or `message_stopped` (ended).

`codex-cli` supports exactly one of those operations — `message_stopped` —
because Codex has no in-turn injection route. Ordinary endings still
worked: Codex fires a `Stop` hook, and a relay-run `codex exec` process
exits when its turn ends, so the relay's process-death report moves the row
to `ended`, whose operation is the one Codex supports.

A turn that ends on a *vendor error* breaks that chain at every link at
once. Observed live: `task_complete` carrying
`{"message": "Selected model is at capacity", "codex_error_info":
"server_overloaded"}`. The process stayed alive, so nothing proved it dead.
No `Stop` hook followed it — the session's last hook event was the
`PostToolUse` two seconds earlier — so posture stayed `running` at the
timestamp of that tool call. Liveness aged `active` → `stale`,
so the router resolved `message_idle`, which `codex-cli` does not support.
The envelope recorded `skipped_operation` and nothing else ever happened:
one session sat unreachable for fifty minutes holding its item claim,
invisible to hook delivery and to the native resume both.

## Why the probe runs on the machine

The turn record that settles the question is Codex's own rollout —
`~/.codex/sessions/YYYY/MM/DD/rollout-<started>-<session_id>.jsonl`, whose
last line is the terminal `task_complete` event. That file lives on the
machine that ran the native, and the wake eligibility sweep runs on the
control plane, which in a hosted install is a different machine entirely.

So the fix is split the way the relay's process-death report already splits:
the control plane names what it cannot see, the machine reads it, and the
control plane applies what came back. `session_control.relay.claim` returns
`turn_end_probes` alongside the poll's jobs; the relay reads those sessions'
records and reports the ended ones through
`session_control.relay.turn_end`; the handler stamps the posture.

Doing it entirely server-side would have worked on a local install and
silently done nothing on the hosted one — a fix that does not fix the
installation where the defect was observed.

## Why the trigger is the recorded skip

Nothing here polls, schedules, or sweeps. A session appears in
`turn_end_probes` only when an envelope addressed to it is still pending and
its own wake attempt already recorded `skipped_operation`. A healthy session
never has such a row, so its rollout is never opened; the read costs nothing
until something has already failed, which is what keeps a per-poll file read
off every machine in the fleet.

## Why the outcome is a posture stamp

The reclassification writes `turn_posture='waiting'` — exactly what the
turn-end hook would have written if Codex fired one — ordered by the record's
own timestamp, so a session that took a real turn after the error keeps its
newer `running` and comes back `posture_superseded`. Nothing downstream
learns a new concept: `waiting` already routes to `message_stopped`, which
is the one operation `codex-cli` supports.

Only `codex-cli` has a reader, because its error-terminal ending is the
only observed turn end that fires no hook. `NATIVE_TURN_RECORD_SURFACES`
names the set, and a report about any other surface is refused as
`surface_without_turn_record` rather than guessed at.

## The observability half

Every wake skip now records the rule that produced it — `skip_reason`, plus
the `wake_operation`, `turn_posture`, and `liveness` it was reading. The
bare `skipped_operation` code covers a surface with no route for the
operation, a peer binary that is not installed, and a driver below its floor;
telling those apart was the first question asked when this session went
quiet, and the recorded attempt could not answer it.

## Related

- [`relay-verified-process-death.md`](relay-verified-process-death.md) — the
  same machine-reports/control-plane-applies shape for a dead process, and
  the evidence boundary refined by
  [`relay-process-death-respects-session-holdings.md`](relay-process-death-respects-session-holdings.md).
