# Steering a Yoke source release

Read only for Yoke self-deploy; `docs/source-dev-doctrine.md` owns the rest.
Records go to prod for both targets. Stage reuses production's `release_lineage`.

```text
yoke --env prod deployment-runs create yoke FLOW --environment prod --idempotency-key KEY
yoke --env prod deployment-runs create yoke STAGE_FLOW --environment stage --source-ref LINEAGE --idempotency-key STAGE_KEY
yoke --env prod-db-admin watch deploy -- PROD_RUN
yoke --env prod watch deploy -- STAGE_RUN
```

Routine calls use `--env prod`; `prod-db-admin` drives only PROD_RUN, trying `prod` first.
Only source-dev provisions prod-db-admin, via `yoke dev db-admin setup`.
Reuse the same run id and key after an interruption.
