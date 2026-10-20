# Steer — batch delivery

Workers merge; the steerer creates runs on the prod control plane. Yoke
self-deploy: read [source-dev-delivery.md](source-dev-delivery.md) first.

```text
yoke --env CONTROL_PLANE deployment-runs create {_project} {PROD_FLOW} --environment prod --idempotency-key PROD_KEY
yoke --env CONTROL_PLANE deployment-runs create {_project} {FLOW} --environment {ENV} --project-repo-path {CHECKOUT} --source-ref {PINNED_SHA} --idempotency-key STAGE_KEY
yoke --env CONTROL_PLANE watch deploy -- {RUN_ID}
```

Stage uses production's exact `release_lineage`. Retry a lost create with the
same key. Stacked migrations rebase in order and ship in one release.

## Member QA

The member's owner runs its QA; never take a live holder's claim.

```text
yoke watch qa-plan -- --deployment-run-id {RUN_ID} --stage STAGE --member PREFIX-N --project {_project}
```

### Manual-wake member QA

Do the owner's check yourself or staff it. If the run cannot produce the
evidence, ask the operator to waive or remove the case; never waive it.

## Orphans

Finish only an orphan handed to this seat; never `--skip-deploy`:

```text
yoke merge item PREFIX-N --result "what shipped" --verification "run evidence"
```
