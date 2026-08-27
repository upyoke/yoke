# A woken turn has to survive long enough to take delivery

A wake does not deliver anything. It starts a turn, and a hook that fires
inside that turn injects the envelope. Three separate things have to hold
for that to end in a receipt: the turn has to survive, the envelope has to
reach the model through a channel the harness actually reads, and nothing
may reap the session in between. A cursor-cli acceptance cell failed with
all three broken at once, and the first two were invisible because the
third produced the loudest symptom.

## What the evidence looked like

A stopped cursor-cli session was woken three times, sixty seconds apart.
Every wake was accepted and settled in about a second. Every one produced
`HarnessSessionResumed`, `HarnessSessionStarted`, and `HarnessSessionEnded`
inside the same second, each end carrying `session_empty_auto_ended`. No
tool call ran, and the injection count stayed at zero until the envelope
timed out.

Read alone, that says the empty-session auto-end reaped the resumed turn.
It was reproduced on the operator's machine with the same session and the
same command, and cancelling the pending message changed nothing: the
auto-end was the consequence of a turn that had already died, not its
cause.

## The turn was dying to a hook wired inside the token stream

Bisected in a scratch workspace whose hooks did nothing but `echo {}`: no
hooks ran clean; every event wired killed the run with `RetriableError:
WritableIterable is closed`; `sessionStart` alone ran clean; and
`afterAgentThought` alone broke the stream once per thought, recovering
only when the reply was short enough to finish inside three reconnects.
`cat > /dev/null; exit 0` and `printf "{}"` broke it too, so no reply shape
saves it.

That event was wired on purpose, and the reasoning was sound when it was
written: on cursor-agent 2026.07.23 it was the only event naming a concrete
model, every other payload reported the `"default"` placeholder, and a
0.04s `echo` hook there measured clean 4/4. On 2026.08.25 both halves of
that reasoning have moved. The affordable-hook budget is zero, and
`sessionStart` and `sessionEnd` now name the real model themselves. So the
hook is deleted rather than made cheaper, and registration reads the model
from the payload that opens the session.

## The envelope was riding a channel Cursor does not read

Cursor answers `sessionStart` with one JSON object. The delivery modules
chose their output channel from a Claude-shaped event set copied into three
files: on `SessionStart` they appended the rendered envelope to raw stdout,
which is exactly right for Claude and unparseable beside a JSON reply. The
envelope reached no model — and because settlement only checks that the
text made it into the process's stdout, the receipt still said `injected`.
Every real cursor injection in the failing run landed on `PostToolUse`;
every `SessionStart` one was recorded as delivered without arriving.

A receipt for a delivery that did not happen is worse than no delivery,
because the control plane stops re-waking on the strength of it. The
channel is now a property of the harness, named once in
`yoke_contracts.hook_runner.model_context_channel`, and an unrecognized
harness gets the structured channel: dropping context with an honest
receipt beats recording one that never arrived.

This matters most exactly where it failed. A stopped session is woken with
`cursor-agent --resume … --print`, and that mode fires only `sessionStart`
and `sessionEnd` — no `beforeSubmitPrompt`, no `stop`. `sessionStart` is
the only chance a woken turn has to receive its envelope before its first
tool call, and the wake prompt tells the turn not to acknowledge an
envelope that never arrived.

## And the auto-end still should not have fired

Between a wake landing and its envelope being acknowledged there is a
window where the session legitimately holds nothing — no claim, no document
lock, no chain budget. That is what the non-destructive end reads as idle.
Ending there reaps the very turn the wake paid for, and the next wake finds
an ended session and repeats the loop, which is what the three attempts
recorded.

`end_session_if_empty` now rates on delivery state as well: a deliverable
recipient on a live message whose last wake is still inside
`fleet.wake_ack_grace_seconds` blocks the end and reports
`wake_delivery_in_flight`. That is the same clock the wake sweep already
uses to decide a delivery is working and needs time rather than another
wake; rating both sides on one clock is what keeps them agreeing. It is a
window, not a hold — a wake that never landed stops protecting the session
once the grace expires.
