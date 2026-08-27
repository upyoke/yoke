# A wake resume carries its own prompt

A fleet wake exists to hand a session a message it has not yet seen. The
handing-over is not the resume: it is the hook that fires *inside* the
resumed turn, because message delivery is a hook decision and a hook only
runs when the turn does something. A resume that reactivates a session and
then ends with no prompt runs no hook, injects nothing, and still reports
success — the plane sees a healthy resume while the envelope sits pending
to expiry.

That is exactly what the Claude wake did. Fleet-launched Claude CLI
sessions are background jobs, and the wake reached them with the native's
`respawn` verb, whose whole contract is "restart a background session so it
picks up the current binary". It takes no prompt. Two acceptance runs
recorded the consequence: the session reactivated (`HarnessSessionResumed`
fired for every attempt) while `injection_count` stayed `0` through
consecutive `resumed_completed` attempts, and the message timed out
unacknowledged.

The healthy adapters were never doing anything cleverer. Cursor and Codex
resume with the wake prompt as the turn's first input, the prompt hook
fires, the envelope is injected, and the session acknowledges on the first
attempt. Claude has the same shape — `-p --resume <session-id> <prompt>`
keeps the session id and appends to the original transcript rather than
forking it.

The one obstacle is why `respawn` was reached for in the first place: the
native refuses a headless resume of a conversation a background job still
holds open (`session is currently running as background agent; attach or
fork`). So the wake stops the job first. Stopping keeps the conversation,
which is what makes the following resume land on the same session rather
than a fork, and the wake scheduler never selects an active session, so no
working agent is stopped by this path. Both facts land on the attempt's
evidence (`background_agent_result`, `background_agent_stop`) so a wake
that failed to free the conversation names itself instead of being read
back from a capture tail.

## The second wake

Delivery arriving on the first attempt is only half of it. A message that
has been injected is not yet acknowledged, and the idleness clock cannot
tell "this session has gone quiet" from "this session is still reading what
it was just handed". Re-wake eligibility therefore also rates on delivery
state: an injected, unacknowledged recipient is left its acknowledgement
window (`fleet.wake_ack_grace_seconds`) before another wake may fire.

Without that window a healthy wake produced a *shape* failure — a first
resume injected, a second wake fired 31 seconds after it completed and
carried the session to acknowledgement, and the receipt then held two
successful wake-kind attempts where the evidence contract requires exactly
one. The contract is the right bar; the cadence was what needed fixing.

## The prompt names the action

Carrying a prompt is necessary and not sufficient. The prompt that was
carried only announced the message — "check your Yoke messages" — and left
the acknowledgement to whatever the resumed turn felt like doing. Which
turn it is turns out to matter: a fleet worker's transcript opens with a
mandate to register and act, so the announcement is enough, and every
worker-born session acknowledged inside its first attempt. A Claude Desktop
conversation has no such mandate. Two consecutive acceptance runs recorded
the same shape on the same desktop session: the first resume injected the
envelope exactly once, ran on for the rest of a minute with no tool call at
all, and ended; the plane then waited out the acknowledgement window and
woke it again, and the second wake carried it to acknowledgement. Delivery
worked. The receipt did not, because its contract requires exactly one
successful wake attempt and this took two.

Cadence could not fix that. By the time the second wake fired, the first
attempt had already reached a terminal settlement, so there was no
in-flight delivery for a suppression window to protect. The missing step
was in the turn, so the prompt now asks for it: run the fixed
acknowledgement command the injected envelope names, before answering or
ending this turn.

It also names the one case where acknowledging is the wrong move. An
unconditional "acknowledge now" would let a wake whose envelope never
arrived report a delivery that did not happen, and the plane would stop
re-waking on the strength of that receipt — trading a shape failure for a
silent one. So the instruction is conditioned on the envelope: no envelope,
no acknowledgement, say so instead.

## One author, one sentence

`expected_native_instruction` exists so a native is handed exactly one
sentence per job and every adapter refuses anything else — "two adapters
spelling it out separately is how a native ends up reading an instruction
the control plane never issued". The Claude adapter was validating the
job's instruction against it and then handing the native a second sentence
of its own, so the digest recorded on the attempt's evidence described text
the native never saw, and the wake prompt could drift from the receipt it
was supposed to earn. Cursor and Codex already deliver the control plane's
sentence verbatim. Claude does now too, which is why strengthening the one
central instruction reaches every harness at once rather than fixing one
surface and leaving the others on the old wording.

## The prompt names the tool call

Naming the acknowledgement was still not enough, because it assumed an
envelope would be there to acknowledge. Delivery is a hook decision, a hook
runs only when the turn calls a tool, and a turn can reason and answer
without calling one. A Cursor session parked idle proved it twice over: two
consecutive fleet acceptance runs failed the same leg, and the second
isolated it exactly — the initial message delivered and acknowledged
normally through the session's own hooks, then a wake envelope sat pending
at `injection_count = 0` through three accepted native resumes, two of them
escalations from the starved-envelope ladder. Each resume produced a turn.
No turn produced a tool call. The prompt now names the call itself, first,
before anything else the turn might do, so the hook that delivers is
guaranteed to run. It is one sentence in one function, so Claude, Codex,
and Cursor all get it from the same place.

## Accepted is not delivered

The prompt makes delivery likely. It cannot make it certain, and the plane
was recording the wrong fact either way. A relay reports what it saw of the
native it started — the resume was accepted, the process is still running,
the process exited — and that observation was written into the field every
reader treats as the outcome. So three resumes that delivered nothing were
three successes, and the receipt they were sent to deliver was the only
place the truth was visible.

A wake attempt is therefore settled by the receipt, never by the relay. A
reported code that leaves delivery unproven keeps the attempt open, exactly
as a detached resume already did, and the control plane closes it from
injection facts: `wake_delivered` when the receipt records an injection or
an acknowledgement after the attempt started, `turn_without_injection` when
the resume finished, or its delivery window elapsed, with the envelope still
pending. The verdict keeps the transport observation beside it, because an
undelivered wake whose native accepted the resume is a different defect from
one whose native never came up.

Naming the failure is what makes the ladder work. An undelivered direct wake
now joins the results that hand the next attempt to the peer-hook broker —
a route that does not depend on the resumed turn calling anything — instead
of reporting a success that stops the plane from trying again.

## The probe rests on delivery, not on having woken

The stale-alive probe ends a session that was asked to report and did not.
It read "asked" as "woken", and a wake that delivers nothing never asked
anything: three resumes against a parked session look, from wake attempts
alone, exactly like three refusals to answer. The end step therefore reads
the probe's own receipt. An undelivered probe ends nothing and says so
(`wake_never_delivered`), leaving the claims to the holdings TTL — slower,
and the only honest verdict available about a session that was never
reached.
