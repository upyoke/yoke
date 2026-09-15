# Resume custody reads activity, not elapsed time

A detached native resume is supervised by a machine-local custody record. Two
readers act on it: the containment sweep, which terminates the process, and
wake reconciliation, which settles the attempt's delivery verdict. Both once
carried an absolute ceiling — one hour from the moment the record was written
— alongside the sustained-quiet check.

The ceiling had no evidence behind it. A resume's age says nothing about
whether its turn is working, and an agent doing real work is exactly the one
that runs longest. Live workers were terminated mid-task twice with `exit 143`
while stamping fresh custody activity the same minute, and reconciliation
settled their attempts as a failure that had not happened.

## The predicate now

A resume is contained when, and only when, one of these holds:

- **It went quiet.** `now - last_activity >= RESUME_INACTIVITY_SECONDS`, where
  `last_activity` is the newest of the custody stamp every hook of that native
  refreshes and the mtime of its capture file. Absent or unreadable evidence
  never counts as activity: it leaves the epoch floor in place, so a resume
  that can prove nothing is contained on the next sweep rather than living
  forever behind a missing file.
- **It is no longer the process the record names.** The recorded process start
  time no longer matches the pid, so the native is already gone and the record
  is reported `already_exited` instead of signalled.

Nothing else reaps a resume. Elapsed time is not a term in either predicate.

Reconciliation mirrors this: a turn still stamping posture or tool calls keeps
its attempt open however long it has been running, and the attempt settles from
activity facts alone — `resumed_died` once activity stops for the quiet window,
`resume_never_started` when there was never any, `turn_without_injection` when
the posture or the resume process says the turn is over.

## What is deliberately unchanged

- **Launch-registration containment.** A native that never registered is
  contained on its own deadline (`CONTAINMENT_TTL_SECONDS`), which is a
  different question — authority, not liveness — and refreshed activity never
  buys an unregistered launch time.
- **Explicit containment.** `contain_launch_native` still reaps a failed create
  immediately, inside any window.
- **Explicit termination and the relay liveness poll** are untouched; a
  registered session's death is observed through its launch handle.

## Why not simply raise the ceiling

A larger number is the same defect further away: it still terminates a healthy
worker on a clock, and it still has to be guessed. The quiet window and the
process-identity check together cover every case the ceiling was reaching for —
an abandoned native, an orphaned one, a resume that never started — with facts
the native itself writes. A resume that stays active is, by that evidence, a
resume that is working.
