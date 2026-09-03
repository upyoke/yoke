# A woken turn reads its message rather than waiting to be handed one

A wake starts a turn so that turn can take delivery of a pending message.
The instruction that turn receives used to name `yoke sessions touch` as the
call to make first, on the reasoning that any tool call fires the installed
hook and the hook attaches the envelope. That reasoning holds for the hook.
It does not hold for *which* turn the hook attaches the envelope to.

## What the evidence looked like

Two workers reported the same shape on the same day. A landing-complete
message was created, a wake attempt opened a second later, and the resumed
process started about half a minute after that. In between, the outgoing
turn — the one that had just exited its merge command and was ending — made
a tool call, its `PreToolUse` hook leased the pending receipt, and the
envelope was injected there. By the time the resumed turn ran the command
the instruction had named, the receipt was `injected` and there was nothing
left to attach. Both workers found their message by hand with
`yoke messages list` and acknowledged it themselves.

The receipts recorded this as a success: an injection after the attempt
opened settles the wake `wake_delivered`, and one had. What it did not
record is that the injection reached a turn that was already ending rather
than the turn the wake had started.

## Why the read moved into the instruction

Hook injection is a push into whatever turn happens to be making tool calls.
A wake is a request for a specific turn. Those two are not the same
addressee, and no amount of ordering inside the hook makes them the same:
the receipt is consumable from the moment it exists, and the wake's own turn
does not begin for tens of seconds.

Reserving the receipt for the resumed process would need the resumed process
to identify itself to the control plane, and the fact that identifies it —
the resume attempt id in the process environment — does not survive into a
relayed hook evaluation, where client-local environment state is by design
unavailable. Re-presenting a consumed receipt to the wake turn needs the
same identity to know which turn is the wake's, and without it either
re-presents to every turn or to none.

So the instruction names a command that returns the message body:
`yoke messages get <id> --json`. It is still a tool call, so the hook still
fires and the envelope may still be injected — that is the same message, not
a second delivery path. What changed is that the turn no longer depends on
the injection happening: the read answers whether or not an earlier turn
consumed the receipt. The acknowledgement command is named in the
instruction for the same reason, rather than being left to an envelope that
may not arrive.

## What this does not change

The delivery verdict is unchanged: an injection *or* an acknowledgement
after the attempt started settles the wake as delivered, and the
acknowledgement the read leads to is exactly that second path. The refusal
to acknowledge a message that was never read stays, because acknowledging a
delivery that did not happen is what stops the plane re-waking.

The earlier finding in
[`woken-turn-survives-to-take-delivery.md`](woken-turn-survives-to-take-delivery.md)
still holds for what it covered — a turn that dies, or never makes a tool
call, delivers nothing. Its opening framing that the hook inside the turn is
what delivers the envelope is the part this record supersedes.
