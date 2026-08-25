# The fleet preflight is enforced by a receipt, not by running it in the release job

## The problem this solves

The fleet migration preflight answers the one question a migration entry
raises: does it still apply to the databases that are behind it? It answers it
well. For a while nothing made anyone ask.

Twice in one day a release shipped an entry nobody had rehearsed against the
fleet, and both times the fleet found out by crash-looping. The preflight
existed for both incidents and reproduced both in one command — *after* the
release. Documentation said to run it. Documentation is not a gate.

## Why the gate is not simply "run the preflight in the release job"

The obvious fix — add a preflight step to the release train — does not fit,
and the reason is physical rather than a matter of taste.

The preflight needs two things at once:

- network reach to the tenant cluster, because it `pg_dump`s each live tenant
  database (read-only); and
- a local embedded Postgres to restore those copies into, which it provisions
  itself.

The release bridge job runs on a GitHub-hosted runner, which has neither.
Moving the job to a runner that has both is a real infrastructure decision with
real consequences, and it was blocking a fix for a failure that had already
happened twice.

## The separation

Two questions were tangled together:

1. **Where does the rehearsal physically execute?** Open. It needs cluster
   reach and an embedded engine, and choosing where those live is an
   infrastructure decision.
2. **Can a build carrying an unrehearsed entry ship?** Closed by this design,
   and independent of the first.

A passing preflight records a receipt naming the environment it rehearsed and
the history entries it covered. Before the release train allocates its tag, it
reads the checked-out history and refuses if any entry is uncovered. Reading
receipts needs no cluster reach and no Postgres, so the gate runs on the hosted
runner that could never host the rehearsal.

The rehearsal can then run anywhere — an operator machine, a self-hosted
runner, a future scheduled job. What changed is that forgetting to run it stops
the release instead of the fleet.

## Why the receipt is an event rather than a table

The events stream is already the durable audit spine, already reachable over
both transports, and already has a query surface with the filters this needs. A
receipt is a fact that something happened at a point in time, which is what
that stream is for. A table would add schema, a reader, and a second thing to
keep consistent, in exchange for nothing this design uses.

The receipt is emitted by the preflight itself and only on a pass, so a receipt
cannot exist for a fleet the rehearsal did not clear. There is no verdict field
to interpret, because a failing run writes nothing.

## Why coverage is a union rather than the newest receipt

A release carries its whole history. Requiring one receipt to cover all of it
would mean re-rehearsing every entry ever written on every release — minutes
per release spent re-proving entries the fleet applied long ago, which is the
kind of cost that gets a gate switched off.

Taking the union across receipts makes the obligation exactly match the risk:
an entry must be rehearsed once for an environment before a build carrying it
ships there, and never again. New entries are what the two incidents had in
common.

Coverage is per environment because each environment is a different fleet
at a different ledger position. An entry that applies cleanly to one says
nothing about another, so a rehearsal of one environment is not evidence
for another.

## Why the gate is before the tag

The tag is the first irreversible act. A release refused after allocation
leaves an annotated tag naming a build that never deployed, plus the artifacts
built against it, plus pin branches already advanced — all of which has
happened and all of which is cleanup nobody chose. Refusing earlier leaves
nothing behind.

## Why unreadable refuses

"No receipt found" and "could not read receipts" are different facts. The first
says the build is unrehearsed. The second says this gate does not know. A gate
that passes when it cannot check is not a gate, and reporting an unanswered
question as a pass is the specific inversion that lets an unrehearsed build
ship. The two produce different messages so the operator can tell which
situation they are in.

## Bootstrapping

With no receipts recorded, every entry is uncovered and the first release is
refused. That is correct rather than an oversight: clearing it is one passing
fleet preflight per environment with `--record-receipt` (the positional names
the fleet to rehearse; `--receipt-env` names the control plane that records
the receipt), which is simultaneously the proof that the fleet is currently
clean. A receipt covers exactly the environment whose fleet was rehearsed;
one environment's receipt never satisfies another. Turning the gate on
therefore requires demonstrating a healthy fleet exactly once.

## Additive schema is the same risk without a history entry

The gate originally keyed coverage only on history entry names. Pure-additive
schema changes never produce an entry, so they shipped as long as every
historical entry had some prior receipt. CI creates fresh databases, where
`CREATE TABLE` covers new columns; aged fleet databases only gain those
columns if boot converge carries an `ALTER`. The fleet preflight already
proves that path, because it converges copies of live databases. The receipt
therefore also records the digest of the source files that emit boot-converge
DDL, and the gate refuses when that digest is uncovered for the target
environment.

Union coverage still applies: a digest is rehearsed once per environment, and
not again until the shape changes. A receipt recorded before this field
existed covers no current digest, which is the bootstrap for the new
obligation — one passing preflight per environment clears it.

## What is deliberately not here

- Where the rehearsal runs. Still an open infrastructure decision, and this
  design is indifferent to the answer.
- Re-rehearsing covered entries as the fleet moves. An entry rehearsed against
  one fleet state is accepted for later releases. Requiring otherwise makes the
  gate cost scale with history length, which is how gates get disabled.
- Recording receipts for anything other than a full-fleet pass. A partial run
  naming specific databases still records the history it covered, and the
  operator who narrows a run is the one accountable for that narrowing.
