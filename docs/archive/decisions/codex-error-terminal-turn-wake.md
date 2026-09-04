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

## Why the trigger was the recorded skip, and why that was not enough

The original trigger was a recorded failure and nothing else: a session
appeared in `turn_end_probes` only when an envelope addressed to it was
still pending and its own wake attempt had already recorded
`skipped_operation`. A healthy session never has such a row, so its rollout
was never opened, which is what kept a per-poll file read off every machine
in the fleet.

That is a delivery fix, and the defect is not only a delivery defect. A
stopped worker nobody happens to be messaging produces no envelope, records
no skip, and so was never probed — it simply went quiet, holding its claim,
until the idle threshold noticed twenty minutes later. On 2026-09-03 five
workers sat exactly that way while the seat read a report that said nothing
was wrong. The trigger is now the union: the recorded skip as before, plus
every live claim-holding session on a surface that keeps a readable record,
still bounded by `MAX_PROBE_TARGETS`, and a session drops out of the set the
moment its posture is stamped. What is read per poll rose from "sessions
with a failure already recorded" to "sessions holding work"; what a claim
holder's silence can hide fell to nothing.

Detection is also no longer the end of it. See
[`vendor-stopped-session-resume.md`](vendor-stopped-session-resume.md) for
what the relay does with a session once it knows the provider stopped it.

## Why the outcome is a posture stamp

The reclassification writes `turn_posture='waiting'` — exactly what the
turn-end hook would have written if Codex fired one — ordered by the record's
own timestamp, so a session that took a real turn after the error keeps its
newer `running` and comes back `posture_superseded`. Nothing downstream
learns a new concept: `waiting` already routes to `message_stopped`, which
is the one operation `codex-cli` supports.

Only `codex-cli` has a reader, because its error-terminal ending is the
only observed turn end that fires no hook. Which surfaces those are is not
a list in this subsystem: each harness family declares a `turn_record`
capability — readable and by what mechanism, or `none` with the reason it
needs none, or `unverified` where nobody has probed — and the readable set
plus the reader table are both derived from those declarations, so a
harness cannot be readable in one and absent from the other. A report about
a surface outside the set is refused as `surface_without_turn_record`
rather than guessed at.

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
