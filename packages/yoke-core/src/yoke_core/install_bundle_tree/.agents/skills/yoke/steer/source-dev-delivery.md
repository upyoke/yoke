# Steering a Yoke source release

Read this only when steering the Yoke source project's self-deploy. The
source checkout's `docs/source-dev-doctrine.md` owns setup, direct database
authority, migration rehearsal, and the release-pair contract.

All real control-plane operations run on prod, including stage-targeted run
records and receipts. Hold `DEPLOY:<project>` before creating or executing
runs and keep it through the pair. Stage drives over HTTPS `prod`; production
uses the configured paired `prod-db-admin` connection because it replaces
the API serving this control plane. The executor's self-deploy refusal names
that connection. Discover it with `yoke env list`; only source-dev/operator
`yoke dev db-admin setup` provisions it.

Create the production run against its CI-tested source, read its exact
`release_lineage`, then give stage that same lineage:

```text
yoke --env prod-db-admin deployment-runs create yoke FLOW \
  --environment prod --idempotency-key KEY
yoke --env prod deployment-runs create yoke STAGE_FLOW \
  --environment stage --source-ref LINEAGE --idempotency-key STAGE_KEY
```

Validate each composition, then drive the runs together through their selected
connections with `yoke watch deploy`. Use the same run id to recover an
interrupted driver. The self-deploy freezes its driver at the recorded lineage;
a source-drift halt requires re-driving that run, not creating another release.
Completion waits for production delivery and every owed stage-targeted proof.
Stage exists here only to test the live control plane; this concurrent pair is
specific to that declaration. Other projects follow their declared delivery
order through their configured HTTPS control plane.
