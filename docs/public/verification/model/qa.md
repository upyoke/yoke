# QA data model

<!-- yoke:breadcrumbs -->
[Yoke](../../index.md) > [Verification](../index.md) > QA model
<!-- /yoke:breadcrumbs -->

Schemas for QA requirements, actual executions and artifact handles. Read [database reference](../../databases/reference.md) for entry points and JSON conventions, and [timestamp discipline](../../databases/migrations.md#timestamp-discipline) for timestamp conventions.

## Table: qa_requirements

Stores QA requirements attached to items, epic tasks, or deployment runs. Each requirement declares what kind of QA must be performed, when in the lifecycle it is due, and what success looks like.

```sql
id INTEGER PRIMARY KEY
item_id INTEGER -- nullable; FK to items(id)
epic_id INTEGER -- nullable; FK to epic_tasks(epic_id)
task_num INTEGER -- nullable; FK to epic_tasks(task_num)
deployment_run_id TEXT -- nullable; FK -> deployment_runs(id)
deployment_stage TEXT -- nullable; pinned deployment QA stage
deployment_member_item_id INTEGER -- nullable; attached item for item-scoped stage QA
qa_kind TEXT NOT NULL -- free-form: implementation_review, simulation, smoke, e2e, visual-regression, etc.
qa_phase TEXT NOT NULL -- CHECK: verification | post_deploy | manual_acceptance
target_env TEXT -- semantic: local | preview | ephemeral | prod
blocking_mode TEXT NOT NULL DEFAULT 'blocking' -- CHECK: blocking | non_blocking
requirement_source TEXT NOT NULL DEFAULT 'explicit' -- CHECK: explicit | seeded_default | ac_derived | flow_derived
success_policy TEXT -- JSON: defines what counts as success (see below)
capability_requirements TEXT -- JSON array: e.g. ["browser","docker","ssh"]
suite_id TEXT -- nullable, unconstrained; links to future test-intelligence suite
waived_at TEXT -- ISO timestamp if waived
waiver_rationale TEXT -- why waived
created_at TEXT NOT NULL
```

**Polymorphic FK constraint:** Exactly one of (`item_id`), (`epic_id` + `task_num`), or (`deployment_run_id`) must be non-NULL. Deployment rows are legacy when stage/member are both NULL; scoped rows require a stage and use a member only for item scope. Enforced by CHECK constraint.

**Indexes:** Base subject indexes remain on item, epic task, and deployment run. Plan-case materialization uses separate partial unique indexes for legacy run, run+stage, and run+stage+member subjects. Scoped keys include the execution-target digest after plan, case key, and host baseline so a superseding receipt preserves old evidence while allowing a fresh exact-target execution.

### success_policy JSON Schema

The registered aggregate policy is all-pass:

```json
{"id":"all-pass","params":{}}
```

Each effective requirement needs a completed passing current actual attempt
with its own definition, review and subject proof. Historical passes and
attempt voting do not rescue a newer failure or pending attempt;
`qa_success_policy_invalid` names the policy correction. A method may measure
thresholds or multiple criteria inside that one attempt. Full policy and
judgment semantics live in [Success policy](../success-policy.md)
and [Requirement state](../requirement-state.md).

## Table: qa_runs

Records actual executions and their history. Gates select the current actual attempt before grading; multiple rows are not votes.

```sql
id INTEGER PRIMARY KEY
qa_requirement_id INTEGER NOT NULL -- FK to qa_requirements(id)
performed_by TEXT NOT NULL -- how it ran: agent, shell, playwright, manual, github-actions
qa_kind TEXT NOT NULL -- what was tested (denormalized from requirement for query convenience)
verdict TEXT -- CHECK: pass | fail | undetermined | error (nullable until inspection writes it)
verdict_reason TEXT -- required when undetermined; agent outcomes also require linked evidence
execution_status TEXT -- CHECK: captured | capture_failed (nullable for non-browser runs)
score REAL -- nullable numeric score
confidence REAL -- nullable confidence level (0.0-1.0)
raw_result TEXT -- → JSONB on Postgres; JSON: full execution output
duration_ms INTEGER -- nullable execution duration
started_at TEXT -- ISO timestamp
completed_at TEXT -- ISO timestamp
created_at TEXT NOT NULL
```

**Index:** `idx_qa_runs_requirement(qa_requirement_id)`

**Capture vs inspection.** For requirements whose `method_id` is
`browser-check` or `browser-inspection`, the two columns serve distinct
concerns:
- `execution_status='captured'` means the daemon successfully saved the expected screenshots to disk.
- `execution_status='capture_failed'` means the daemon errored, an artifact path was missing, a step failed, or completeness check failed.
- `verdict` is set **only after screenshot inspection** (LLM or human evaluation of the screenshot content). Infrastructure success alone never writes `verdict='pass'`.
- Typical lifecycle: `yoke qa case run --requirement-id <id>` records the
  method's execution result. An evidence-backed Browser inspection can remain
  undetermined, halting the item until a project owner/operator resolves its
  `qa_needs_review` request. Missing evidence is an execution failure and asks no human.

Every downstream gate that filters `verdict='pass'` (status-transition, pre-merge, pre-deploy, flow-gate updates) therefore gates on inspection outcome, not capture.

**Evidence currency:** a pass must answer for the exact code and frozen
target the gate evaluates. Commit-time ordering or an unavailable branch is
not identity proof. The [case attachment contract](../case-attachment.md)
owns immutable target binding, receipt supersession and candidate checkout;
the [QA platform](../platform.md) owns current gate and evidence rules.
Stale or out-of-scope evidence retains its history and names the rerun or
rebind recovery rather than satisfying a different candidate.

## Table: qa_artifacts

Links binary/text artifacts (screenshots, diffs, logs, traces) to a QA run.

```sql
id INTEGER PRIMARY KEY
qa_run_id INTEGER NOT NULL -- FK to qa_runs(id)
artifact_type TEXT NOT NULL -- screenshot, diff_image, log, trace, etc.
content_type TEXT -- MIME type: image/png, text/plain, etc.
artifact_handle TEXT -- typed handle JSON: {"backend":"s3","bucket":B,"key":K} or {"backend":"local","path":P}
metadata TEXT -- → JSONB on Postgres; JSON: dimensions, file size, etc.
created_at TEXT NOT NULL
```

**Index:** `idx_qa_artifacts_run(qa_run_id)`

**Artifact handles:** `artifact_handle` is the only file reference — a typed
JSON document naming where bytes live. All submitted files and inline bytes use
the configured project S3 store; upload completes before its row is recorded.
Only a genuinely unconfigured bucket selects permanent server-local storage;
hosted tenants use `YOKE_QA_ARTIFACT_BROKER_URL`, `YOKE_QA_ARTIFACT_BROKER_TOKEN_FILE`,
`YOKE_QA_ARTIFACT_BUCKET`, and immutable `YOKE_QA_ARTIFACT_PREFIX` settings.
Invalid configured storage returns its real error without a row or local
downgrade. Existing readable local handles and repo baselines remain supported,
but bare paths are refused. Gates check local files and accept valid S3 handles
structurally without an added network call.

## Related

- [QA CLI](../qa-cli.md)
- [Session model](../../sessions/model/sessions.md)
- [Shared coordination](../../sessions/model/coordination.md)
- [Release entries](../../deployments/model/releases.md#table-release_entries)
- [Merge locks](../../items/model/landings.md#table-merge_locks)
