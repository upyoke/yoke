# The QA gate adopts an existing run instead of making the verdict write survive

## What happened

A CI-routed QA case run polls its GitHub workflow run for 13-14 minutes.
The local watcher driving that poll is killed at agent turn boundaries —
its raw capture says `interrupted by signal 15; child process group
reaped` — and the verdict-writing step never ran. The CI run itself
completed green on GitHub's side, but nothing joined the two afterwards,
so the only recovery was a fresh full CI execution of a byte-identical
tree. It happened twice on one item inside an hour, and the observing
session read the watcher's silence as "CI is probably still running"
while the run had already passed.

The gate run is the project's single canonical full execution, and the
local admission slot is a shared resource, so a discarded run costs every
other item queued behind it as well as its own wall clock.

## The decision

Before dispatching, the gate asks GitHub what has already happened to the
exact commit under test, and the answer picks the path: adopt a run that
already reached a verdict, attach to one still in flight, dispatch only an
unexamined commit. `ci_run_source` records which happened.

GitHub's run record, keyed by workflow and head SHA, is the durable state
this relies on. The gate does not need its own memory of what it started,
because the authority that ran the suite already has one.

## Two alternatives considered and declined

**Making the verdict write survive the watcher's own teardown.** The
stronger-sounding fix, and the one to reach for if the gap were between
"the run concluded" and "the verdict is recorded" — but it is not. That
window is milliseconds. The exposed window is the 13-14 minutes of
polling, during which there is no verdict to make durable: a signal
handler firing then can only record that the gate was interrupted, and
recording an `error` verdict for a run that later passes is worse than
recording nothing. Closing the real window means the poll must outlive
the process, which is the next alternative.

**Detaching the gate so a turn boundary cannot signal it** (the
`os.setsid()` workaround a worker improvised). This turns `yoke qa case
run` from a command that returns a verdict into one that returns a
promise, and every caller — the skills, the lifecycle gates, the
watchers, an operator at a terminal — is written against the former. It
would also need a rendezvous to collect the verdict later, which is the
adoption path above wearing a second hat. Adoption gets the same
recovery for one API lookup and leaves the command's contract intact.

**A local "dispatched, awaiting verdict" row** was the third option, and
it is what attachment replaces. Its stated value was letting the next
invocation see that a run is already in flight; the covering-run lookup
sees that from GitHub directly, without a second source of truth that can
drift from the run it describes.

## What would change the decision

If a project's CI provider stopped exposing runs by commit, adoption
would lose its authority and the local in-flight record would become the
only way to answer the same question.
