# A desktop conversation is woken by the person reading it

## What went wrong

A steering seat replied to a Claude Desktop session with `yoke say
--session`. The message was real, the delivery machinery worked, and the
outcome was still wrong: the relay resumed the session headlessly
(`claude -p --resume`), the reply was processed, and the Desktop app showed
those turns only after a refresh. The operator's next typed sentence
continued from the app's own last turn instead, so the conversation forked —
two branches, each convinced it was the transcript.

Nothing failed loudly. The receipt said the wake succeeded, because by its
own definition it had.

## Why a peer binary made it possible

Every Claude app on one machine shares a transcript store, so the installed
CLI can resume a session whichever app registered it. That is exactly what
makes a stopped `claude-cli` worker recoverable, and exactly what makes a
desktop window forkable: the same route, told apart only by whose window it
is. Cursor's desktop conversations had the same shape through `cursor-cli`.

The capability matrix could not express the difference. `claude-desktop`
already declared `message_stopped: none`, and the peer-executor rule read
past that declaration on purpose — "the surface the session registered under
has no resume route of its own" was the reason to substitute the CLI, not a
reason to stop.

## The fact that settles it

`wake_authority` on each surface capability: `native`, or `operator`. Every
desktop surface declares `operator`, which is rendered into
`session_control.surfaces` in the harness manifest and read by the wake path
rather than inferred from a route. It outranks every version floor and every
installed peer binary, because no upgrade and no neighbouring process changes
whose window it is.

Four chokepoints consume it, and each is a place a wake could otherwise have
been reconstructed: `surface_operation_supported` (no wake operation at any
version), `machine_wake_executor_surface` (no peer binary named),
`authorize_wake_versions` (no one-shot stage grant reopens it), and
`_native_wake_route_available` (no private-route qualification reopens it).
One predicate, `native_wake_supported`, so the answer cannot differ between
them.

## Delivery is unchanged; only the resume is refused

A desktop session still receives messages. Its hooks still run, and the
pending envelope still attaches on the operator's next turn — the route was
never the problem. What is gone is the attempt to manufacture that turn.

## The absence had to be reported to someone

Refusing the resume without saying anything would trade a forked transcript
for a silent one. So past the same `fleet.wake_ack_grace_seconds` every other
starvation test uses, the session's own operator gets an actor-addressed
Inbox message naming the waiting conversation and the one action that
delivers it: type anything in that chat. The steering fleet report's starved
row carries `operator_wake` and says the same thing instead of a revive
recipe, and the dashboard session card reads "waiting for the operator to
wake it".

This is the one deliberate exception to the zero-touch stance in
[`starved-envelope-native-resume.md`](starved-envelope-native-resume.md).
That decision's escalation fires a wake because a wake exists to fire; here
there is no wake to fire, and the only actor who can end the wait is a
person. Asking them is not a page bolted onto an automatic path — it *is*
the path.

## What was removed

The `cursor-desktop` → `cursor-cli` peer wake route, entirely. It existed
only to resume a desktop conversation, which is now the thing that never
happens; leaving it behind a flag would have preserved a route with no
caller and a second answer to the same question.
