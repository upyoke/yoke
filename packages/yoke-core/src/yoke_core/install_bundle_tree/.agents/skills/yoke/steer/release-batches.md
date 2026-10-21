# Steer — batch delivery

Workers merge; the steerer creates runs on the prod control plane. Yoke
self-deploy: read [source-dev-delivery.md](source-dev-delivery.md) first.

```text
yoke --env CONTROL_PLANE deployment-runs create {_project} {PROD_FLOW} --environment prod --idempotency-key PROD_KEY
yoke --env CONTROL_PLANE deployment-runs get {RUN_ID} release_lineage
yoke --env CONTROL_PLANE deployment-runs create {_project} {FLOW} --environment {ENV} --project-repo-path {CHECKOUT} --source-ref {PINNED_SHA} --idempotency-key STAGE_KEY
yoke --env CONTROL_PLANE watch deploy -- {RUN_ID}
```

CONTROL_PLANE is https; a database env refuses `use_https_env`. Stage
uses production's exact `release_lineage`. Retry a lost create with its
key; re-drive with the same `watch deploy`. Migrations:
`databases.md`.

## Member QA

The member's owner runs its QA; never take its claim. The driver logs `Still
waiting for scoped QA` per minute and exits 5 at timeout; longer silence is
stuck: re-drive on exit. Stop a walk via `yoke qa plan abort`; never kill
its runner.

```text
yoke watch qa-plan -- --deployment-run-id {RUN_ID} --stage STAGE --member PREFIX-N --project {_project}
```

### Manual-wake member QA

Do or staff the owner's check; `yoke qa plan reconcile` an ownerless
walk. Lacking evidence, have the operator waive or remove the case;
never waive it.

The driver owns run-scoped QA:

```text
yoke watch qa-plan -- --deployment-run-id {RUN_ID} --stage STAGE --project {_project}
```

## Orphans

Finish only an orphan handed to this seat; never `--skip-deploy`:

```text
yoke claims work acquire --item PREFIX-N --reason "orphaned release-wait member"
yoke merge item PREFIX-N --result "what shipped" --verification "run evidence"
```
