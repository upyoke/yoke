# Shared-operation holds are work claims, not a second lock table

Yoke ran two lock systems side by side. `work_claims` coordinated backlog
work: typed targets, session binding, heartbeat, a stale-session sweep,
telemetry, the board's Claims column, and packet teaching. A second table
coordinated everything else — migration territory for one model, one
physical test machine, one private-route qualification grant — keyed on
`(project_id, lease_key)` with its own owner columns, its own listing and
recovery modules, its own doctor checks, and its own CLI.

Every feature the second table grew was a feature the first one already
had. Typed ownership arrived there months after claims had it, in a
different shape (`owner_kind` plus three nullable owner columns) that
readers then had to branch on. Board rendering, session-holdings reads,
and the stale-session sweep each carried a second code path whose only
job was to ask the same question of a different table.

## What replaced it

Three `work_claims` target kinds, each with a validated JSON scope:

| Kind | Scope | Coordinates |
|---|---|---|
| `migration_serialization` | `{project_id, model, item_id}` | Migration territory for one model |
| `qa_admission` | `{machine_id}` | One physical test machine |
| `route_qualification` | `{project_id, grant_key}` | One qualification grant |

Two design points are worth keeping in mind.

**`qa_admission` has no project in scope, on purpose.** A physical test
machine is one resource whichever project drives the run, but a lease was
unique per `(project_id, lease_key)`. Bridging that gap took a whole
module: every host lease was anchored to the project that registered the
machine, plus a registration guard keeping that anchor well defined. With
the machine alone in scope the anchor has nothing to do, and it is gone.
The registration guard stays — one physical host belonging to one project
is a real product rule, independent of how the hold is stored.

**`migration_serialization` conflicts on `(project_id, model)`, not on
its whole scope.** The owning item rides in the scope because the hold is
item-owned and has to survive session end, but it is not part of what is
held: one model in one project admits one live claim whichever item took
it. This reuses the mechanism `process` claims already had, where the
exclusivity unit is narrower than the scope, rather than adding a second
one.

## Stickiness is the property that actually differed

The one thing leases had that claims did not was liveness policy. A
backlog claim is reclaimed when its holder goes stale, because the work
cannot continue without that session. A migration mid-authorship and a
remote suite mid-run keep going after the session that started them goes
quiet — reclaiming those hands a live resource to a second holder, which
is exactly why operator-driven lease recovery existed at all.

That is now per-kind policy (`STICKY_TARGET_KINDS`) that the stale-session
sweep, the session-end release, and the claim-free end check all consult.
`route_qualification` is deliberately not sticky: a grant is only valid
while its operator session lives, so the sweep should reclaim it, and it
did before.

Staleness *reporting* stays independent of stickiness. A sticky
session-held claim still reports a stale holder to a waiter and to doctor
— what stickiness removes is the automatic release, not the signal. An
item-owned hold reports no staleness at all, because there is no session
liveness to read.

## What the migration had to be careful about

The governed entry folds instead of duplicating. A universe can serve the
new build before the entry applies, which means the running code has
already written the claim row the entry would produce; re-inserting it
would trip the new exclusivity index. Where the equivalent live claim
exists, the lease row is dropped rather than migrated.

A hold whose acquiring session no longer exists in `harness_sessions`
cannot become a claim row — claims are session-bound by foreign key, and
inventing a holder would attribute a resource to a session that never
took it. Those rows settle with the table: the resource frees, and the
next caller acquires it cleanly. Stranding it behind a fabricated holder
would have been the worse failure, because only an operator could then
clear it.

## What stayed

The operator recovery path is unchanged in shape and in guarantees: a
WARN `OperatorLeaseRelease` event lands *before* the release mutation so
a telemetry outage cannot mask a successful operator action, the command
refuses to run from a hook context, and the operator's words stay
permanently on the row — now in `release_reason_intent`, beside the
closed `release_reason` vocabulary claims already had.

Operator keys stayed too. `LIVE_DB_MIGRATION:<model>` and
`QA_HOST:<machine>` are what a human types when recovering a stranded
resource, and a JSON scope is not. `coordination_claim_keys` is the only
place the two representations convert, so a key never means two things.
