# A migration ledger must answer membership, not a threshold

## The gap this closes

A project declaring a `migration_model` says where its migration modules
live, what database they run against, and what surface rehearsal uses. It
says nothing about how *applied-ness* is decided. That omission is
load-bearing: a project can satisfy every authoring gate, every rehearsal,
and every compatibility check, and then apply its migrations through a
reader whose semantics silently skip entries.

The unsound reader is a **high-water mark** — store the highest version
that ran, treat everything above it as pending. It was found live in an
external project whose runner computed pending as
`version > (SELECT MAX(version) FROM schema_version)`.

## Why a threshold is refused rather than warned about

It loses three different ways, and none of them announce themselves:

1. **A skipped entry becomes permanently invisible.** If `003` fails or is
   skipped while `004` succeeds, the mark is 4, and nothing above 4 ever
   includes 3 again. The entry is not late; it is gone.
2. **A rollback reports itself current.** The mark still names the newer
   entry, so an older build computes an empty pending set while reading a
   schema it does not know. This is the same failure class
   `MINIMUM_SERVING_VERSION` exists to prevent, and a threshold cannot
   express the floor either: there is no per-entry row to carry it.
3. **Out-of-order merges drop an entry.** Two branches each add a numbered
   module; if the higher number lands first, the lower is never pending.

Membership answers all three, because the pending set is
`history - applied` and an entry is pending exactly when its own identity
is absent. Order in the history decides *when* an entry runs, never
*whether* it is owed.

A warning was considered and rejected. A warning leaves the unsound reader
in place while implying it has been reviewed, which is strictly worse than
either refusing it or saying nothing: the operator gets the feeling of
having a check without having one. That is the same shape as the failures
this whole area keeps producing — a confident-looking signal about
something the signal cannot actually see.

## What the contract requires

A ledger declaration names its `table`, its `entry_column`, its
`semantics`, and its `serving_floor_column`. `semantics` accepts only
`membership`. The serving floor is required once a ledger is declared:
membership alone cannot stop a rolled-back build from serving a database
it cannot read — see `project-migration-rollback-safety.md`.

The declaration is validated **when present**, not required outright.
Models predating this contract are already deployed, and refusing them
would add a check by taking working projects down. New and amended models
are refused on the spot.

## Why the declaration is checked against reality

A declaration is a promise. `HC-project-migration-ledger-contract` reads
the live ledger rows and reports whether they satisfy the rollback-safety
contract (membership plus a readable serving floor) for the shipped
history. Three outcomes stay distinct on purpose:

- **N/A** — the model declares no ledger. An absent opinion is not a
  failure.
- **WARN** — the ledger cannot be read, or the packaged history cannot be
  parsed. "I could not read it" and "it is level" are opposite answers, and
  only one of them is safe to assume.
- **FAIL** — entries are unapplied, or the ledger names entries the history
  does not contain. The second means the ledger and the history are not
  describing the same migration set, which makes every pending answer
  meaningless rather than merely stale.

## Scope

This constrains the contract Yoke owns. Changing any individual project's
own runner to read membership is that project's work, in that project's
repository, under its own work item.
