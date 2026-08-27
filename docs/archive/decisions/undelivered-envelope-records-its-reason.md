# An envelope that goes undelivered records which step declined

A hook that attaches no message is the ordinary case: most events reach a
session whose inbox is empty, and saying so on every one of them would cost
a write per tool call for no reader. So every declining path returned
quietly, and the quiet was indistinguishable from the expensive case — a
receipt sitting `pending` for that exact session while an event that could
have carried it passed through and carried nothing.

## What the absence cost

A stopped cursor-cli session was woken, and the wake was accepted. The
session recorded `HarnessSessionResumed` and `HarnessSessionStarted`
seventeen seconds later and then stopped: no tool call, no further hook,
`injection_count` still zero eighteen minutes on, the receipt still
`pending`. Its wake budget was already spent, so nothing tried again and
the envelope was stranded for good.

Everything in that paragraph is a symptom. Not one row said which step
declined, and there were four candidates that produce it identically: the
session's stored surface refusing the event, a lease losing its row-lock
race against the wake sweep, a statement failing inside the lease and being
swallowed by a blanket `except`, or the hook never running at all. Telling
those apart decides whether the fix belongs to eligibility, to lock
ordering, to error handling, or to the harness — and the evidence could
not distinguish them, so the work item that carried this failure had to
name its mechanism "inferred".

Live re-execution ruled the fourth candidate out and, in doing so, settled
the question the failure had put to the delivery path itself: a Cursor
session that had ended, been sent a message, and then received a
`sessionStart` took the envelope on the first evaluation, in one valid
JSON reply, and acknowledged it. There is no separate resumed-start path
to repair. The evaluator is told the event and the session and never
whether the session is opening or reopening, which is exactly why a resume
reaches the same lease a first turn does. The hook-side probe suite holds
that property so a later change cannot quietly grow a second path.

## What is recorded, and what deliberately is not

Three reasons, each a fact about the moment rather than about
configuration, written as a `session_message_attempts` row against the
receipt that went unattached:

- `probe_session_not_deliverable` — the lease refused this session for
  this event.
- `probe_no_leasable_receipt` — a lease opened and came back with nothing
  to carry.
- `probe_lease_failed` — the lease raised, with the exception's class
  recorded and never its message.

Two silent exits stay silent. A session this process cannot name has
nothing to key a record on. An event the harness cannot inject on is
already answered by the capability table, and probing it would spend a
write on every tool call of every session with a pending message.

The row goes in the table an operator already reads to follow a message,
so the reason appears beside the wake and injection attempts rather than
in a surface someone has to know to look at. Its identifier is derived
from the receipt, the session, the event, and the reason, so a repeated
decline folds into the row it already wrote instead of growing one per
hook. `hook_event` and `probe_detail` were added to the shared evidence
whitelist for the same reason: a fact that the message view redacts away
is not diagnosable, and that whitelist gap had already been silently
dropping `hook_event` from every ordinary delivery attempt.

Writing the reason is best-effort. Whatever stopped the delivery may
equally stop the write, and a hook that fails because its diagnostics
failed is a worse outcome than the missing row.
