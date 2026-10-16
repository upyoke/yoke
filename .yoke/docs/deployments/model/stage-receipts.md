# Deployment stage receipts

<!-- yoke:breadcrumbs -->
[Yoke](../../index.md) > [Deployments](../index.md) > Stage receipts
<!-- /yoke:breadcrumbs -->

Inspect durable deployment-stage attempt observations and the evidence required before scoped QA.

## Table: deployment_stage_receipts

Durable executor observations for non-QA deployment-stage attempts. Events do
not substitute for this authority.

```sql
id INTEGER PRIMARY KEY
run_id TEXT NOT NULL REFERENCES deployment_runs(id)
stage_name TEXT NOT NULL
attempt_number INTEGER NOT NULL -- allocated before dispatch; increasing per run/stage
correlation_id TEXT NOT NULL -- idempotency key for one dispatch
target_kind TEXT NOT NULL -- persistent_environment | run_preview
target_name TEXT -- required when ready
status TEXT NOT NULL -- pending | ready | failed | cancelled
observed_url TEXT
observed_release_lineage TEXT -- required when ready; exact run candidate
observed_artifact_identity TEXT -- must match when the run pins an artifact
executor TEXT NOT NULL
executor_receipt TEXT
failure_reason TEXT -- required when failed or cancelled
created_at TEXT NOT NULL
completed_at TEXT -- required when ready
UNIQUE(run_id, stage_name, attempt_number)
UNIQUE(run_id, stage_name, correlation_id)
```

The attempt number, rather than row insertion order, determines the current
observation. A repeated correlation is accepted only with identical immutable
dispatch inputs, and a terminal callback cannot change its evidence. Scoped QA
consumes only the latest ready attempt from the QA target's earlier
`source_stage`, with the exact target and release lineage and, when the run pins
one, the exact artifact identity. A delayed older success cannot override a
newer failure, and a superseded receipt cannot revalidate an accepted execution
or later-stage prerequisite. Run-preview readiness requires an observed URL;
command-only persistent environments do not.

Who fills those observed columns is a per-target-kind decision,
registered in `deploy_pipeline_stage_receipt_producers.RECEIPT_PRODUCERS`.
Each producer takes one `ProducerContext` (the stage, its QA target, the
run and stage names, the project, the dispatch correlation id and the
dispatch callable) and returns a `StageObservation`: target name,
observed release lineage, optionally an observed URL and artifact identity. The
step runner's diagnostic travels to `executor_receipt` instead, so a producer
that reads a served URL and commit back reports them structurally rather than
encoding them in one string. An empty observed-identity column is not a gap to
fill with whatever string is at hand — the store compares observed against
pinned, so an invented value refuses the receipt, and a run pinning an artifact
identity no producer reads back is refused before the stage dispatches. The
registry's key set *is* the supported-target-kind list.

Release verification and notices — how release-to-done reads both QA
authorities, who observes a stage receipt, and the verdict and owner
notices — live in [releases.md](releases.md).

## Related

- [Runs](runs.md)
- [Run members](run-members.md)
