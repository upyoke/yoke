# One native per session turn

## What happened

A session held one work claim and ran three overlapping native processes
inside twenty-seven minutes. A wake started the first at 06:50:23 and it ran
until 07:17:02. An automatic message about a failed CI run started a second
at 07:03:09; a message about the succeeding run started a third at 07:13:45.
All three interleaved tests, a commit, a rebase, and lifecycle writes against
one worktree.

Each wake was individually correct on the evidence its decider had. The
control plane escalates a pending envelope to a native resume when the
recipient's hook route has demonstrably stopped: no injection since the
message arrived, and no tool call for a full acknowledgement grace window.
The session's last tool call had completed at 07:00:10 and the message
arrived at 07:03:07, so by that reading the route was absent.

It was not. The turn was waiting on an armed wake subscription for the very
CI run the message was about. A turn between tool calls — reasoning,
streaming, or holding a subscription — runs no hook and closes no row, and
the only counter-evidence the escalation consults is an *open*
`session_tool_calls` row. There was none, because the last call had returned
normally.

## Why the control plane cannot fix this

Everything the escalation reads is a clock: a heartbeat, a last tool call, a
message creation time. Quiet has two causes those cannot separate — a
process thinking, and a process gone — which is the same ambiguity the
staleness TTL exists to wait out elsewhere. Lengthening the window trades one
failure for the other: too short forks the conversation, too long strands the
envelope the escalation exists to deliver.

## Where the fact actually lives

The machine that would start the second native started the first one, and
kept its pid with the process start time beside it. Two record families
already carried that, written for other readers:

- the resume custody record the relay writes for every native it resumes,
  released only once that native exits and its outcome is reported;
- the launch handle the hook writes when a launched native registers.

Both are custody: this machine started a headless native that exits when its
turn ends, so its pid still naming that process means the turn is running.
The check therefore sits in the one shared relay job runner every harness's
wake passes through, before any surface adapter can spawn. The comparison is
against the recorded start time, so a reused pid reads as gone rather than as
alive, and a session with no record at all proves nothing and is left alone.

The process-anchor registry is deliberately excluded. An anchor names a
process for any session, including an operator's own interactive one, where a
live process means a person has a window open and not that a turn is
executing — deferring on it would leave an idle interactive session's
envelope undelivered. An operator-opened interactive session is therefore not
covered by this guard, which remains the narrower correct answer over one
that trades this defect for a starvation.

## What a declined wake owes the envelope

Nothing is started, so nothing is delivered and nothing failed. The reported
outcome is its own code rather than a failure, because reading it as one
tells an operator a wake broke where the relay made the right call.

The attempt is charged to the recipient at claim time, before the relay runs
— which is right for a wake that goes on to start something and wrong for one
declined. Left charged, a long turn would walk its own message to
`max_wake_attempts` and make it unwakeable for exactly the reason it was held
back, so the settlement gives the attempt back and pushes `wake_after`
forward one window. The backoff is not politeness: a machine claims one wake
job per poll, so a recipient that re-qualifies immediately would hold that
single slot for the whole running turn and queue every other session's wake
behind a decision already made.

That refund is what makes the settling write's atomicity matter. Reading the
attempt open and then writing it is two steps, and two copies of one report
can both pass the read before either writes; the write therefore carries its
own unsettled predicate and only the copy that wins it refunds. The refund
also declines while any other wake attempt is open against the recipient,
because a newer claim owns the budget and the backoff by then.
