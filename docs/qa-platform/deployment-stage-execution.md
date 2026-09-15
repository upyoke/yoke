# Deployment QA Stage Execution

Schema-2 deployment flows may pause on ordered QA stages whose durable subject
is the frozen deployment run, stage name, and optional attached member. These
stages reuse `qa_plan_executions` for roster/cursor ownership,
`qa_requirements` for concrete obligations, and `qa_runs` plus `qa_artifacts`
for evidence. They do not create another release, scheduler, or verdict store.

Run scope executes once for the combined release. Item scope executes once per
frozen member against the same deployed preview, stage, or production target:

```text
yoke qa plan run \
  --deployment-run-id <run-id> \
  --stage <stage-name> \
  [--member <PREFIX-N>] \
  [--plan <agent-selected-project-plan>] \
  --project <project>
```

The member flag is required for item scope and forbidden for run scope. Named
flow cases and selected member requirements come from the run's immutable
admission snapshots. If no concrete method case was admitted or configured,
the executor supplies `--plan`; its frozen cases are materialized separately
from admitted aggregate obligations, so evidence retains both identities.

Every requirement and execution carries `deployment_stage`; item scope also
carries `deployment_member_item_id`. Legacy deployment-run rows keep both NULL.
Each QA target names `source_stage`, an earlier non-QA stage whose executor
produces a durable `deployment_stage_receipts` attempt before dispatch. Attempt
numbers are allocated under the run lock; a repeated correlation ID is
idempotent only when its immutable dispatch inputs match. The latest attempt is
authoritative even when an older callback arrives later. Only a latest `ready`
attempt with the exact target and release lineage can start QA; when the run
pins an artifact identity, the receipt must observe that exact artifact too.
Run-preview receipts must also carry the observed URL; command-only persistent
targets may omit one.

Materialization records the resolved tenant, project, configured environment,
site and endpoints together with the receipt ID, attempt, correlation, observed
URL/revision/artifact, run, QA stage, member, `release_lineage`, and artifact
identity in the existing execution-target snapshot. Generic projects resolve
their registered environment settings; there are no Yoke-hostname or fixed
stage/production assumptions. Every execution and result write re-resolves the
frozen receipt and refuses if it was superseded, failed, cancelled, changed
target, or changed candidate. Historical evidence stays attached to the old
execution and cannot settle a replacement or satisfy a later-stage prerequisite.

All concrete blocking cases must pass with evidence attached to the exact
execution capture, or carry an explicit waiver, before stage acceptance.
Admitted aggregate obligations require their own explicit passing result linked
to evidence artifacts from concrete cases in that execution; case success is
never copied into an automatic obligation pass. `agent_only` requires a
conclusive agent verdict.
`human_if_unsure` creates authorized Inbox work only after an evidence-backed
undetermined case verdict. `required_human` waits until every case passes, then
creates one whole-stage acceptance request using the configured project roles,
named actors, and ANY/ALL mode. Item-stage acceptance for every member is a
hard prerequisite for later run-scoped QA. Resume/from-stage and flow failure
policy cannot skip these acceptances.

Advanced definitions remain disabled while
`CURRENT_EXECUTION_SCHEMA_VERSION` is 1. Enabling schema 2 belongs to the
coordinated lifecycle/runtime rollout after its consumers are verified. The
receipt table and read/write contract are additive, but no current flow writes
receipts until that rollout lands its executor integration.

## Governed cutover

Migration `0043_scoped_deployment_qa_execution` adds nullable stage/member
columns, replaces only recognized legacy subject checks, and replaces the old
run-wide active/materialization indexes with separate legacy, run-stage, and
member-stage partial unique indexes. It rewrites no historical row. Its serving
floor is `NEXT_RELEASE` because an old boot can recreate the retired run-wide
index.

Permitted deployment order is: drain every old serving build; boot the new
release so additive convergence runs; apply the ordered migration; then admit
scoped writers after exact hosted-consumer verification. A binary-only rollback
after migration is forbidden. To return to old binaries, stop the new build and
restore the pre-migration database backup first.
