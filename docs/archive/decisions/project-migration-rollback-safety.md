# Membership alone is not rollback-safe; the serving floor is the other half

## The gap this closes

A project can declare a membership ledger, pass
`HC-project-migration-ledger-contract`, and still do the exact thing Yoke's
migration design exists to prevent: roll back past a destructive entry,
report itself current, serve, and read a surface that is not there.

Membership-by-name is deliberate and must not change. A rolled-back build's
history genuinely lacks the newer entry, so the pending set is empty — that
answer is correct by the build's own lights, and fatal. Head equality would
brick the rollback direction, which is worse. So membership cannot be the
whole of rollback safety.

## What the serving floor adds

A destructive entry declares the oldest build that may serve against the
database after it runs. The applier copies that floor into the ledger row
at apply time. A build too old to ship the entry module reads the floor
from the row — the only surface the two builds share — and refuses to
serve when stranded.

Accordingly, an older artifact may be membership-current while its ledger has
names outside the packaged history. That is safe only when its artifact
version satisfies every recorded floor. A diagnostic without artifact-version
evidence reports the comparison as unknown; it never rejects the newer names
by themselves.

The two mechanisms only work together:

| Mechanism | Answers | Alone, fails when |
|---|---|---|
| Membership by name | "Have I applied everything I ship?" | A rolled-back build ships less history than the database has applied |
| Serving floor on the row | "Am I too old to serve this database?" | Nothing records a floor, or nothing reads it |

## What a declaring project must do

This is a contract Yoke owns and teaches; changing any individual project's
runner is that project's work.

1. **Boot answers before serving.** Is the pending set empty? Is any
   applied floor newer than this build? Refuse when either answer is
   unsafe.
2. **Record per applied entry.** Entry identity for membership, plus the
   serving floor copied from a surface-removing entry's declared minimum
   (empty only when that entry did not remove a surface).
3. **Declare every element.** `table`, `entry_column`,
   `semantics=membership`, and `serving_floor_column`. The ledger and floor
   are mandatory; an omitted or unconsumed column is the path that leaves a
   project unable to answer rollback safety.

## How an operator can tell

`HC-project-migration-ledger-contract` reports whether the selected project
satisfies the contract against its declared history, database, and live rows.
Unreadable stays a finding
(WARN), never a PASS: "I could not read it" and "it is level" are opposite
answers.

## Scope

Yoke's own `applied_migrations` semantics and `/v1/health`
`can_serve_this_database` already implement this for Yoke. Building a
hosted health endpoint on an external project's behalf is out of scope.
See also `project-migration-ledger-contract.md` (membership vs threshold)
and `ordered-cumulative-migrations.md` (Yoke's floor copy at apply).
