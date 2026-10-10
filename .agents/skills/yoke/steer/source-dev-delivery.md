# Steering a Yoke source release

Read only for Yoke self-deploy; source docs/source-dev-doctrine.md owns setup,
operator database authority, rehearsal and release-pair contract.
All real records/receipts are prod, including stage-targeted work. Hold
DEPLOY:project through creation/execution and both runs. Stage drives on HTTPS
prod; production uses configured paired prod-db-admin because it replaces
the serving API. Its refusal names that connection; discover with yoke env list.
Only source-dev/operator provisions it through yoke dev db-admin setup.

Production binds CI-tested source. Read its exact release_lineage, then use
that same lineage for stage:

```text
yoke --env prod-db-admin deployment-runs create yoke FLOW --environment prod --idempotency-key KEY
yoke --env prod deployment-runs create yoke STAGE_FLOW --environment stage --source-ref LINEAGE --idempotency-key STAGE_KEY
```

Validate each composition and drive concurrently through its selected
connection with yoke watch deploy. Interrupted/drifted driver reuses the same
run id and frozen lineage, never a new unrelated release. Completion waits
for production and all owed stage-targeted proofs. Stage here tests the live
control plane; other projects keep their declared order on configured HTTPS.
