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
