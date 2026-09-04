# A worker the model provider stopped is told to keep going, three times

## What happened

On 2026-09-03, between 15:03 and 15:14Z, five of eight steering-launched
workers stopped. Their turns ended on `task_complete` carrying `unexpected
status 404 Not Found` against the provider's own endpoint. Nothing was
wrong with any of them: the provider had stopped serving the client build
they were running — the desktop app's bundled `codex 0.151.0-alpha.7.2` —
and when that app auto-updated to `0.152.1` and restarted around 15:19Z,
resumes worked again. Three sibling workers running under a different
process owner never noticed, because they were already mid-connection.

Twenty minutes into that, the fleet report showed idle-holder rows and
nothing else, and a person hand-wrote five resume messages. Two of those
resumes died within seconds on the same failure, and the report could not
say so.

Three separate things had to be true for that outcome, and each is a
decision recorded below.

## The turn record is read for every claim holder, not only for the stuck

Detection is covered in
[`codex-error-terminal-turn-wake.md`](codex-error-terminal-turn-wake.md):
the read used to be triggered by a delivery that had already failed, which
means a stopped worker nobody was messaging was never looked at. It now
runs for every live claim holder on a surface that keeps a record.

## Whether to retry comes from the failure, not from a counter

The provider refuses for reasons that differ in exactly one way that
matters: whether running the same turn again could possibly work. A
capacity refusal or a client build the provider has stopped serving will
succeed later untouched. An exhausted quota or rejected credentials will
not, no matter how many times it is tried — the fix is on the account, and
attempts against it are pure spend plus a report row that looks handled
while nobody is handling it.

So classification is one shared ordered list of signatures — vendor codes
and message patterns in, a signature id plus a retryable flag out — and not
a branch per message at each call site. An unrecognized failure classifies
as unclassified and retryable: the failure this exists for arrived carrying
only `codex_error_info: "other"`, so a design that recovers only recognized
failures would not have recovered the incident that produced it.

## Three attempts, and what counts as one

The waits widen — one minute, five, fifteen — because a provider that just
refused will almost certainly refuse again immediately, and in the observed
incident it was the fifteen-minute mark that landed after the real fix.

Counting attempts needed no column. A resume is counted when its event is
newer than the session's own last tool call. That single test carries the
distinction the whole budget rests on: a resume that produced real work
pushes `last_tool_call_at` past its own event and the budget resets, because
a worker that got something done and later hit the provider again is not the
same stuck worker; a resume that died seconds after injection leaves the
last tool call behind it and spends one of the same three.

Counting from the newest failure instead would look equivalent and would be
an unbounded retry loop: every fresh refusal would reset the budget, which
is precisely the spend loop the budget exists to prevent.

## The version that matters is the one installed now

The incident was cured by a binary being replaced under a running fleet. A
session's recorded `executor_version` is the version it started with, so a
resume stamped with that would name the build that failed rather than the
build that ran. Each resume reads the version the machine's relay reports
having at that moment, records both it and the previous value on the event,
and corrects the session row when they differ — because version-gated
routing reads that row afterwards, and the resume is what made it stale.

## A session inside a tool call is never resumed

An unreturned tool call is a turn that is executing. No hook fires during
it, so every absence-based test reads it as a silent session, and one such
session was natively resumed while it sat inside a merge command started
twenty minutes earlier. Nothing forked that time; the general shape is a
second turn on one conversation.

So an open `session_tool_calls` row blocks the native resume outright, on
both paths that could start one, and the report says the recipient's turn is
in flight rather than showing an unexplained failure. It is deliberately not
counted as actionable: a long call would otherwise raise the alarm for its
whole length, which is how a real finding gets ignored. Open rows are closed
at session end by the orphaned-tool-call sweep, so a dead session cannot use
a stranded row to shield itself forever.

## When the budget is gone, the row says so

Nothing silently gives up. A spent budget, and a failure no retry can move,
both keep their row and name the seat as the next actor — and only those
rows make the report actionable. A fleet the relay is already working
through reads as context, so the section stays worth reading on the day it
finally contains something nobody is coming for.

## Related

- [`codex-error-terminal-turn-wake.md`](codex-error-terminal-turn-wake.md) —
  how a stopped turn is detected at all, and why the machine reads the
  record while the control plane applies it.
- [`relay-verified-process-death.md`](relay-verified-process-death.md) — the
  same machine-reports/control-plane-applies shape for a dead process.
