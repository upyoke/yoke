# Steering a Yoke source release

Read only for Yoke self-deploy; source docs/source-dev-doctrine.md owns setup,
operator database authority, rehearsal and release-pair contract.
All real records/receipts are prod, including stage-targeted work. Runs take
no claim; each occupies its target servers until its QA settles.
Create, validate composition and take over through HTTPS prod for both targets.
Stage execution also uses HTTPS prod. Production watch-deploy/execute uses
configured paired prod-db-admin when it replaces the serving API; its refusal
names that connection. Discover it with yoke env list. Only source-dev/operator
provisions it through yoke dev db-admin setup. Both connections address the
same prod run records.

Production binds CI-tested source. Read its exact release_lineage, then use
that same lineage for stage:

```text
yoke --env prod deployment-runs create yoke FLOW --environment prod --idempotency-key KEY
yoke --env prod deployment-runs create yoke STAGE_FLOW --environment stage --source-ref LINEAGE --idempotency-key STAGE_KEY
yoke --env prod deployment-runs validate-composition PROD_RUN
yoke --env prod deployment-runs validate-composition STAGE_RUN
yoke --env prod-db-admin watch deploy -- PROD_RUN
yoke --env prod watch deploy -- STAGE_RUN
```

Keep a live creation request running. Resolve an uncertain outcome before any
recovery, preserving its idempotency key; changing transport is not authority
to create a competing run. Explicit source-operator creation through paired
admin is only for a required creation correction the serving API predates;
follow the bootstrap recipe in docs/source-dev-doctrine.md.

Drive the pair concurrently. Both drivers re-exec into the frozen release
commit, so no local CLI install precedes a release, even one adding a migration
or changing machine config; the prod relay installs the released CLI once prod
serves it. Interrupted/drifted driver reuses the same run id and frozen lineage,
never a new unrelated release. Completion waits for production and all owed
stage-targeted proofs. Stage here tests the live control plane; other projects
keep their declared order on configured HTTPS.
