# An active session is not always a served session

## What went wrong

A pending envelope sat 53 minutes against a session the control plane
labelled `active`, with `injection_count` still at zero. Four hours later a
second envelope did the same thing to the same session. Neither was a slow
delivery. Both were a route that had ended while the machinery kept waiting
on it.

## Why the machinery waited

Two facts were being conflated. Liveness measures the heartbeat; hook
delivery needs the *turn* to tick, because a hook only runs when the session
calls a tool. Those normally move together, which is why the wake sweep could
treat `active` as "this session serves itself" and skip it outright:

```python
if liveness == "active":
    continue
```

They come apart whenever a turn stops calling tools while something still
refreshes the heartbeat — parked mid-turn, blocked outside the harness,
waiting on input nobody types. The session reads `active` forever, the sweep
defers forever, and the envelope is starved by a route that will never run
again. No amount of retrying the hook route fixes it, because the hook route
is not slow — it is absent.

## What the envelope proves

The receipt carries the evidence, so nothing has to be inferred about the
session's inner state. Zero injections past the acknowledgement grace window
says little on its own; a session with no work to do also injects nothing.
What closes it is the recipient's own clock: **no tool call since the message
was created** means no hook has run for that session since it arrived, and a
hook is the only thing that could have attached the envelope. The window is
measured from that last tool call rather than from the send, so silence the
recipient had already accrued counts — see
[`wake-attempt-and-diagnosis.md`](wake-attempt-and-diagnosis.md) for why
counting from the send abandoned four steering waits in one night.

At that point the wake escalates to the stopped-session native-resume path,
even though liveness still reads active. The predicate lives in
`session_message_starvation.py` and the branch in `wake_eligible_recipients`;
`session_liveness` is deliberately untouched, so this composes with — rather
than competes against — any later work that reclassifies such sessions.

## Design choices worth keeping

**No new `WakeMode`.** The escalated candidate reports `WakeMode.WAITING`,
which `wake_operation` already maps to `message_stopped` on every relay
binary in the fleet, including ones older than this change. A third enum
value would have been more expressive and would have failed
`normalize_wake_mode` on any relay that had not been updated yet — a feature
that silently does nothing during its own rollout, which is the failure this
repository's sequencing rule exists to prevent.

**The claim guards bend for the escalation, and only for it.**
`claim_wake_attempt` refuses an `active` candidate, and refuses a `WAITING`
wake whose recipient is not actually parked. Both refusals say the same
thing: never resume a session that is about to collect the envelope through
its own hooks. The escalation is the evidence that it will not, so it is the
one caller allowed past them. Safety does not rest on the flag — the CAS
still pins the session's own `last_tool_call_at`, so a session that ticks
between eligibility and lease loses the claim to its own recovery.

**One wake per recipient per window.** The resume spawns a real process, and
two racing each other is the failure mode that matters. `last_wake_at` plus
the same grace window bounds it, with an explicit bypass for the broker
adoption path — that caller reserves first and re-derives the candidate
afterwards, so its own stamped wake would otherwise disqualify the escalation
it is carrying out.

**Zero touch.** The escalation fires the wake itself. There is no operator
page and no approval step; the reason rides on the wake attempt's evidence so
an escalated resume can be told apart from an ordinary one after the fact,
and a wake that fails records its failure the way every other wake does.

Zero touch holds wherever a wake exists to fire, which is every headless CLI
surface. It does not hold for a desktop conversation, which Yoke never
resumes at all — see
[`desktop-sessions-are-operator-woken.md`](desktop-sessions-are-operator-woken.md).
There the only actor who can end the wait is the person reading the window,
so the escalation becomes a message to them rather than a resume.
