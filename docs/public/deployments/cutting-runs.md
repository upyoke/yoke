# Cutting runs and release sets

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Deployments](index.md) > Cutting runs
<!-- /yoke:breadcrumbs -->

Read who creates runs, how one command creates a release set, and what a run
cut behind a busy server does.

## Who cuts runs

A run is cut, meaning created, in one of two ways:

- **Item delivery.** `/yoke usher PREFIX-N` or
  `yoke deployment-runs start-for-item` delivers one item. It binds the
  CI-proven gate branch tip exactly as `create` does, takes over a waiting
  run on its target, inserts the item's membership and validates composition
  in one transaction. A refusal at any step writes nothing. It returns the run
  already holding or carrying the item (`reused`) rather than starting a
  second one. `bound_release_in_flight` names another project's live release
  that ships this source without the item: let it finish, then run
  start-for-item again ([commit proof](../verification/success-policy.md#commit-proof)).
- **Release batches.** Steering cuts one release set for a batch of items.
  A worker whose delivery steering batches starts no run of its own.

A driver then executes the run with `yoke watch deploy -- RUN-ID`. Flow ID is
not run ID: runs are named `run-YYYYMMDD-NNN`.

## Create a release set

To release one commit through several flows, name each flow in one create:

```sh
yoke --env CONTROL-PLANE deployment-runs create PROJECT STAGE-FLOW PRODUCTION-FLOW --idempotency-key RELEASE-KEY
```

With no source options, the set binds one gate branch tip, read from a flow
that waits for CI: a tip whose only CI ran in the merge queue gets one CI
dispatch, and every flow releases that commit. To choose a commit, pass
`--project-repo-path CHECKOUT --source-ref FULL_SHA` once. Each run gets the
key `RELEASE-KEY:FLOW` and its own flow's environment, so `--environment` and
`--retry-of` are refused.

The set is all or nothing: if any flow refuses, no run is created and no
older run is taken over, so repeating the same command with the same key
creates the whole set. Name only flows that may start now, and drive each
run; your flows and QA gates decide any order. When a correction lands,
create a new release set on its passing commit; earlier Stage proof does not
cover the correction.

## Release pairs

Yoke's own Stage and Production runs are cut together by habit, as one
release pair from one create and one commit. Each run of the pair runs on its
own. Neither waits for the other, each has its own driver, and each owes its
own QA. A stage-only obligation does not hold the production run, and a
production obligation does not keep an item out of the stage run
([settlement](settlement.md#each-run-settles-on-its-own-target)).

## Release policy at creation

`deployment-runs create` prints the project's execution instructions that
select When creating release, once per call: a release set prints them once,
not per run, and a replayed create prints them again. Read and obey them
before you execute the runs. JSON returns them as `execution_instructions`;
an older server omits the field and prints nothing. `watch deploy` does not
repeat them. See [execution instructions](../projects/execution-instructions.md).

## Idempotent creation

`deployment_runs.create` takes a caller `idempotency_key` (CLI
`--idempotency-key`, required there) naming the one run the call intends. It
is stored on that run as `create_idempotency_key`, unique per project, with
the canonical request in `create_request`, both written inside the creation
transaction.

- A repeat with the same key and request returns the original run with
  `replayed: true`, even after the lock was released.
- The same key with a changed input refuses `idempotency_key_conflict`,
  naming the run and the differing fields.
- A key whose run was cancelled before it started creates a fresh run. One
  cancelled after it started still returns that run, so a deliberate cancel
  is never recreated.
- A deliberate second run of the same candidate takes a new key.

A create that yielded is usually still running: continue it, and repeat with
the same key only once it really exited without a run ID. The CLI waits up to
60 seconds for the create response (the hosted path allows 70). When that
times out, it repeats the create once under the same key and reports the run
it recovered as a `deployment_run_create_timeout_recovered` warning; a second
timeout is reported with the instruction to re-run the identical command. The
receipt reports `idempotency_basis=recorded_key` for a keyed request and null
when unkeyed.

## A run cut behind a busy server waits

Only one run deploys to a server at a time. A run occupies the origin of
every environment it targets from the moment it is marked `executing` until
its QA stages have settled or it ends
([target occupancy](model/run-members.md#target-occupancy-serializes-deploys-no-claim-is-taken)).

A run cut while another run still deploys there is not started over it. When
the busy run waits only on QA, the newer run takes it over
([takeover](takeover.md)). When it is still deploying, the newer run stays
`created`, names the older run in `waiting_for_run_id`, and its start refuses
with `target_occupied`, naming the origin, the holding run and its open QA
lines. Re-run the start once the holder finishes deploying and its QA
settles, or terminalize a holder nobody will finish.

Creating and executing a run take no claim. Creation serializes against other
creation for the same project under a transaction-scoped advisory lock.

## Related

- [Deployments overview](index.md)
- [How a run picks its members](model/run-composition.md)
- [Start diagnostics](start-diagnostics.md)
