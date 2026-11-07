# Steer — batch delivery

Create runs through the connection owning the project.

Resolve the intended full commit once and verify its CI passed. Create the
project's release set in one command, listing its flows in order; each flow
owns its environment. Respect any declared QA gate before creating a flow
that it must precede.

```sh
PINNED_SHA=$(git -C "$CHECKOUT" rev-parse HEAD)
yoke --env CONTROL_PLANE deployment-runs create PROJECT FLOW_A FLOW_B --project-repo-path "$CHECKOUT" --source-ref "$PINNED_SHA" --idempotency-key RELEASE_KEY
yoke --env CONTROL_PLANE watch deploy -- RUN_ID
```

Every run records that commit and key `RELEASE_KEY:FLOW`. A refusal cancels
runs already made by the call. A correction needs a new set on its passing
commit; earlier proof does not cover it. For tip binding and the Yoke project's
release-set example, see `.yoke/docs/deployments/index.md#create-a-release-set`.

Cut while member QA runs; keep the execution ID (`.yoke/docs/deployments/model/run-members.md`).

CONTROL_PLANE is the project-owning HTTPS connection (`--env`, or checkout routing);
DB env refuses run creation with `use_https_env`. Both targets use the selected
source `release_lineage`. A self-replacing run uses the paired `*-db-admin`
driver: `stage-db-admin` for Stage ownership, `prod-db-admin` for Production. Retry lost creates with the same key; re-drive with
`watch deploy`. Migrations: `.yoke/docs/databases/index.md`.

## Member QA

The owner runs member QA and keeps its claim. The driver logs `Still waiting
for scoped QA` per minute, exits 5 at timeout, then re-drives; longer silence
is stuck. Stop with `yoke qa plan abort`, never kill the runner.

```text
yoke watch qa-plan -- --item PREFIX-N --stage STAGE --project {_project}
```

Failed QA: `.yoke/docs/verification/failed-item-qa.md`.

### Manual-wake member QA

Staff owners; `yoke qa plan reconcile` ownerless walks. Evidence not available on this release yet: stay parked;
the case rides the next release takeover.

Driver runs run-scoped QA:

```text
yoke watch qa-plan -- --deployment-run-id {RUN_ID} --stage STAGE --project {_project}
```

## Orphans

Finish only an orphan handed here; never `--skip-deploy`:

```text
yoke claims work acquire --item PREFIX-N --reason "orphaned release-wait member"
yoke merge item PREFIX-N --result "what shipped" --verification "run evidence"
```
