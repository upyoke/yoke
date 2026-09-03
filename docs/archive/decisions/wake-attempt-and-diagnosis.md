# A wake nobody attempted, and a failure nobody named

## What happened

In one night four steering waits were abandoned by hand. Each time a
steering seat had launched a worker, the worker armed a landing and stopped
calling tools, the seat sent it a close-out message, and the message sat
pending. The seat waited, saw a holder going quiet and an envelope that
never moved, terminated the session, and finished the close-out itself.

Two independent defects produced that identical picture, and neither was
visible from the surfaces a seat reads.

## The wake that was never attempted

The escalation that resumes a session whose hook route has stopped running
waited an acknowledgement grace window — five minutes — measured from the
moment the message was created. But the fact the window exists to establish
is that no hook is running for the recipient, and the recipient's own clock
had already established it: in the clearest case the worker's last tool call
was seventeen minutes before the message was even sent.

Counting from the send restarted that wait on every new message. A worker
already silent for seventeen minutes bought its envelope another five
minutes of nothing, and three of the four seats gave up inside that window.

The window is now a silence window on the recipient's clock:
`last_tool_call_at + grace`, so silence accrued before the message counts
toward it. It reduces to the old behaviour in the ordinary case, where the
recipient was working right up to the send.

## The failure that named nothing

The other case did get an attempt — and it failed, along with every other
native wake on that machine for two hours, with `RESULT: failed` and an
empty `DIAGNOSTIC` column.

The reason was in the evidence the whole time. The Claude relay adapter
rebuilt the wake instruction from its own build of `yoke_contracts` and
refused the job unless the control plane's sentence compared equal to it.
A commit had changed that sentence's wording. The relay was running it; the
control plane it talks to was not yet. Every wake refused with
`instruction_invalid`, and the fleet report and the message table both
showed only the coarse `failed` the attempt row stores.

Two things follow from that.

**The wording is no longer the test.** An equality check against a
locally-recomputed sentence is a build lockstep that neither side declares,
and this repository's own sequencing rule says a slice must survive its own
rollout. The adapter now checks the one thing it can check without owning
the text — that the sentence names this job's target — and hands the control
plane's own bytes to the native. That is also strictly closer to the
property the check was written for: the sentence has one author, and it is
now literally the author's bytes that arrive rather than a copy that
happened to compare equal.

**A failed attempt always names a reason.** One helper, shared by the
message table and the fleet report, resolves the named reason out of the
evidence — the adapter's refusal code, the eligibility rule that skipped the
route, a server-side closure — and falls back to a literal `unreported` when
an attempt truly carried nothing. There is no longer a failure that renders
as an empty column.

## What the seat sees now

The starved-delivery section stopped waiting a flat ten minutes on envelope
age. A zero-attempt envelope appears one relay poll after the plane owed an
attempt — that is, one poll after the recipient's silence passed the grace
window — and says `no delivery attempted`. A failed attempt appears at once
whatever the age, and names its diagnostic. Those are opposite findings: one
says the plane skipped the receipt, the other names a refusal to go fix, and
before this the seat could not tell them apart from the report.

## One direct retry after an undelivered turn

`turn_without_injection` used to hand the receipt straight to the peer-hook
broker, because delivery depended on the resumed turn making a tool call of
its own and a turn that answers in prose makes none. The wake instruction no
longer depends on that: it names the command that returns the message body
as the turn's first action. So a single undelivered turn is now evidence
that one turn ignored its instruction rather than that the route is closed,
and the direct route gets one more try before the broker takes over. A
second one is the route, and hands off.
