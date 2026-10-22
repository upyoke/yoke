# Steer — batch delivery

Workers merge; steering creates runs on prod. For Yoke self-deploy, read
[source-dev-delivery.md](source-dev-delivery.md).

```text
yoke --env CONTROL_PLANE deployment-runs create {_project} {PROD_FLOW} --environment prod --idempotency-key PROD_KEY
yoke --env CONTROL_PLANE deployment-runs get {RUN_ID} release_lineage
yoke --env CONTROL_PLANE deployment-runs create {_project} {FLOW} --environment {ENV} --project-repo-path {CHECKOUT} --source-ref {PINNED_SHA} --idempotency-key STAGE_KEY
yoke --env CONTROL_PLANE watch deploy -- {RUN_ID}
```

CONTROL_PLANE is HTTPS; DB env refuses `use_https_env`. Stage uses production's
`release_lineage`. Retry lost creates with the same key; re-drive with
`watch deploy`. Migrations: `databases.md`.

## Member QA

The owner runs member QA and keeps its claim. The driver logs `Still waiting
for scoped QA` per minute and exits 5 at timeout; re-drive on exit. Longer
silence is stuck. Stop walks via `yoke qa plan abort`, never kill the runner.

```text
yoke watch qa-plan -- --item PREFIX-N --stage STAGE --project {_project}
```

Failed QA: `.yoke/docs/verification/failed-item-qa.md`.

### Manual-wake member QA

Staff owners; `yoke qa plan reconcile` ownerless walks. Without evidence,
ask the operator to waive or remove the case; never waive it.

Driver runs run-scoped QA:

```text
yoke watch qa-plan -- --deployment-run-id {RUN_ID} --stage STAGE --project {_project}
```

## Orphans

Finish only an orphan handed to this seat; never `--skip-deploy`:

```text
yoke claims work acquire --item PREFIX-N --reason "orphaned release-wait member"
yoke merge item PREFIX-N --result "what shipped" --verification "run evidence"
```
