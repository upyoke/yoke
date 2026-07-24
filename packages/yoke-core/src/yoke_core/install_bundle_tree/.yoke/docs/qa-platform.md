# QA Platform

Yoke's QA platform replaces the legacy `reviews` table with a unified, requirement-driven quality assurance model. Every item must carry explicit QA requirements before it can enter the review lane (`reviewing-implementation` in the current lifecycle). QA results are recorded as typed runs with non-binary verdicts, artifacts, and codified success policies.

Agent writes against the QA tables route through the Yoke function-call
surface (`qa.requirement.add`, `qa.requirement.add_batch`,
`qa.requirement.auto_create_for_item`, `qa.requirement.list`,
`qa.requirement.get`, `qa.requirement.update`, `qa.run.add`,
`qa.run.complete`, `qa.run.record_verdict`, `qa.run.list`,
`qa.artifact.presign`, `qa.artifact.add`, `qa.gate_summary.run`,
`qa.browser_context.get`, `qa.screenshot_evidence.pending_count`, and
`qa.screenshot_evidence.satisfy`). The public `yoke qa ...` commands in
[qa-platform/cli-reference.md](qa-platform/cli-reference.md) are the retained
operator/debug adapters that dispatch the matching function ids. See
[.yoke/docs/db-reference/functions.md](db-reference/functions.md) for the envelope
and, for the operator-readable Atlas of registered
surfaces, the yoke source-repo doc `docs/atlas.md`.

## Four-Layer Model

QA is modeled in four independent layers. These layers are independent columns/fields -- never collapse them into a single enum.

### Layer 1: qa_kind -- What are we proving?

Free-form text describing the kind of QA being performed.

| Value | Description |
|-------|-------------|
| `implementation_review` | Code/spec review by Tester agent (migrated from legacy `reviews` table) |
| `simulation` | Cross-task integration simulation |
| `smoke` | Post-deploy smoke test (HTTP health checks, basic flows) |
| `e2e` | End-to-end browser test scenario |
| `visual-regression` | Visual diff against known-good baseline |
| `manual-acceptance` | Human sign-off on acceptance criteria |

New qa_kinds can be added without schema changes. The column is free-form text, not a CHECK-constrained enum.

### Layer 2: executor_type -- How is it run?

| Value | Description |
|-------|-------------|
| `agent` | Claude agent (Tester, Simulator) executes and judges |
| `shell` | Shell script execution (`exit_code == 0` = pass) |
| `playwright` | Playwright browser automation framework |
| `manual` | Human performs the QA step and records result |
| `github-actions` | GitHub Actions workflow execution |
| `remote-browser` | Remote browser service (screenshot capture, DOM inspection) |

### Layer 3: capability_requirements -- What runtime access is needed?

JSON array of capability slugs. The deployment pipeline checks these against `project_capabilities` before execution.

```json
["browser", "docker", "ssh", "repo", "github"]
```

An empty array or NULL means no special capabilities are required.

### Layer 4: success_policy -- What counts as success?

JSON object defining the acceptance criteria for the QA requirement. Supports non-binary, statistical, and composite assessments. See [success_policy JSON Schema](#success_policy-json-schema) below.

## Table Schemas

### qa_requirements

Stores QA requirements attached to items, epic tasks, or deployment runs. Each requirement declares what kind of QA must be performed, when in the lifecycle it is due, and what success looks like.

```sql
id INTEGER PRIMARY KEY
item_id INTEGER -- nullable; FK to items(id)
epic_id INTEGER -- nullable; FK to epic_tasks(epic_id)
task_num INTEGER -- nullable; FK to epic_tasks(task_num)
deployment_run_id TEXT -- nullable; no FK (deployment_runs table deferred)
qa_kind TEXT NOT NULL -- free-form: implementation_review, simulation, smoke, e2e, visual-regression, etc.
qa_phase TEXT NOT NULL -- CHECK: verification | post_deploy | manual_acceptance
target_env TEXT -- semantic: local | preview | ephemeral | prod
blocking_mode TEXT NOT NULL DEFAULT 'blocking' -- CHECK: blocking | non_blocking
requirement_source TEXT NOT NULL DEFAULT 'explicit' -- CHECK: explicit | seeded_default | ac_derived | flow_derived
success_policy TEXT -- JSON: defines what counts as success
capability_requirements TEXT -- JSON array: e.g. ["browser","docker","ssh"]
suite_id TEXT -- nullable, unconstrained; links to future test-intelligence suite
waived_at TEXT -- ISO timestamp if waived
waiver_rationale TEXT -- why waived
waiver_source TEXT -- 'operator' or 'agent'
created_at TEXT NOT NULL
```

**Polymorphic FK constraint:** Exactly one of (`item_id`), (`epic_id` + `task_num`), or (`deployment_run_id`) must be non-NULL:

```sql
CHECK (
 (item_id IS NOT NULL AND epic_id IS NULL AND task_num IS NULL AND deployment_run_id IS NULL) OR
 (item_id IS NULL AND epic_id IS NOT NULL AND task_num IS NOT NULL AND deployment_run_id IS NULL) OR
 (item_id IS NULL AND epic_id IS NULL AND task_num IS NULL AND deployment_run_id IS NOT NULL)
)
```

**Indexes:** `idx_qa_requirements_item(item_id)`, `idx_qa_requirements_epic(epic_id, task_num)`, `idx_qa_requirements_deployment(deployment_run_id)`

### qa_runs

Records individual QA executions against a requirement. Multiple runs per requirement support statistical success policies.

```sql
id INTEGER PRIMARY KEY
qa_requirement_id INTEGER NOT NULL -- FK to qa_requirements(id)
executor_type TEXT NOT NULL -- how it ran: agent, shell, playwright, manual, github-actions, remote-browser
qa_kind TEXT NOT NULL -- denormalized from requirement for query convenience
verdict TEXT -- CHECK: pass | fail | inconclusive | error (nullable: started but not completed)
score REAL -- nullable numeric score
confidence REAL -- nullable confidence level (0.0-1.0)
raw_result TEXT -- → JSONB on Postgres; JSON: full execution output; browser_substrate runs also record code_identity.branch / code_identity.sha
duration_ms INTEGER -- nullable execution duration
started_at TEXT -- ISO timestamp
completed_at TEXT -- ISO timestamp
created_at TEXT NOT NULL
```

**Index:** `idx_qa_runs_requirement(qa_requirement_id)`

### qa_artifacts

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
JSON document naming where the bytes live. `s3` handles are durable evidence
uploaded at record time (the orchestrator mints a presigned PUT via
`qa.artifact.presign`, uploads, then records); `local` handles explicitly
declare machine-local evidence (tests, manual fallbacks, repo-committed
baselines). Bare paths are refused by `qa.artifact.add`. Gates verify `local`
handles on disk and accept well-formed `s3` handles structurally (the upload
preceded the record; lifecycle gates add no network calls).


## success_policy JSON Schema

The `success_policy` column on `qa_requirements` stores a JSON object defining what counts as success. Five policy types are supported (`deterministic`, `threshold`, `statistical`, `composite`, `agent_judgment`); each has its own JSON shape, semantics, and evaluation rules. Full schema and decision logic per type live in [qa-platform/success-policy-schema.md](qa-platform/success-policy-schema.md). Downstream consumers (conduct, usher) implement policy evaluation; a centralized evaluation engine is deferred.

## QA Phases

`qa_phase` is a controlled vocabulary meaning "when in the delivery/implementation lifecycle this requirement becomes due."

| Phase | When Due | Gating Effect |
|-------|----------|---------------|
| `verification` | During conduct/tester verification, before `reviewed-implementation` | Blocks the `reviewed-implementation` transition |
| `post_deploy` | After a deployment run completes to target env | Blocks `done` transition |
| `manual_acceptance` | After automated QA, requires human sign-off | Blocks `done` transition |

## Target Environments

`target_env` is a semantic selector resolved to a concrete environment at runtime.

| Value | Description |
|-------|-------------|
| `local` | No Yoke environment record required |
| `preview` | Named non-production target (e.g., staging, qa, shmaging) |
| `ephemeral` | Short-lived branch/item-scoped environment |
| `prod` | Production environment |

Notes:
- `preview` and `ephemeral` are distinct -- one is not shorthand for the other.
- Concrete preview names (staging, qa, shmaging) are preview-environment names, not separate `target_env` enum values.
- Preview environments may participate in delivery-time targeting; ephemeral environments are branch/item-scoped validation infrastructure.
- Not every project has every target environment.
- Detailed browser-environment semantics are canonical.

## Blocking Modes

| Value | Gating Effect |
|-------|---------------|
| `blocking` | Unsatisfied requirement prevents status transition |
| `non_blocking` | Requirement is tracked but does not prevent transitions |

## Requirement Sources

`requirement_source` tracks where the requirement came from.

| Value | Description |
|-------|-------------|
| `explicit` | Manually declared by operator or shepherd |
| `seeded_default` | Auto-seeded by project/item-type policy |
| `ac_derived` | Derived from acceptance criteria (e.g., AC -> browser check) |
| `flow_derived` | Materialized from deployment flow definition |

## Gating Semantics

### Validation Entry Guard

When an item or task transitions to `reviewing-implementation`, the system checks that at least one `qa_requirements` row exists. If zero exist, the transition is rejected with a clear error message.

**Implementation:** `yoke_core.domain.qa_gates` enforces this during the
lifecycle transition. Operators can inspect the public requirement read surface
with `yoke qa requirement list --item YOK-N`.

### Review-Complete Gate

Transitioning to `reviewed-implementation` requires all blocking `verification`-phase requirements to have at least one passing run (or be waived).

**Public preview:** `yoke qa gate-summary --item YOK-N --target reviewed-implementation --json`

A requirement is "satisfied" if:
- It has at least one `qa_runs` row with `verdict='pass'`, OR
- It has been waived (`waived_at IS NOT NULL`)

### Done Gate

Transitioning to `done` requires all blocking `post_deploy` and `manual_acceptance` phase requirements to be satisfied (same pass/waive logic).

**Public preview:** `yoke qa gate-summary --item YOK-N --target implemented --json`

### Bypass

Set `YOKE_QA_GATE_BYPASS=1` to bypass all gates (for force operations).

## Requirement Materialization

### Item-Level Requirements

Issue and epic items must have materialized item-level requirements before entering the QA-gated review lane. The shepherd skill or seeded defaults attach these during item definition.

### Epic Task Requirements

Epic tasks may carry task-level requirements for task execution and verification. Task-level blocking requirements gate that task's `reviewed-implementation` and `done` transitions. Epic tasks now mirror parent epic statuses including `release` — tasks cascade through `release` when the parent epic enters the release phase.

### Epic Parent Aggregation

An epic parent item cannot become `reviewed-implementation` until:
- All blocking epic-task verification requirements are satisfied
- All blocking epic-level requirements are satisfied

### Deployment Run Requirements

Deployment runs materialize run-level requirements when the run is created. These are flow- or release-scoped post-deploy requirements that prove release health.

## Browser QA Modes

The schema supports three browser-QA assessment modes under the same normalized model:

### Deterministic Assertions

Exact computed values (color, selector visibility, HTTP status).

```json
{
 "qa_kind": "e2e",
 "executor_type": "playwright",
 "success_policy": {"type": "deterministic", "check": "exit_code", "expected": 0}
}
```

### Diff-Aware Baseline Comparison

Visual diff against a known-good render.

```json
{
 "qa_kind": "visual-regression",
 "executor_type": "remote-browser",
 "success_policy": {"type": "threshold", "metric": "diff_pct", "threshold": 5.0, "operator": "lte"}
}
```

### Agent-Judged Visual Acceptance

LLM-based screenshot judgment for higher-level acceptance criteria.

```json
{
 "qa_kind": "e2e",
 "executor_type": "agent",
 "success_policy": {
 "type": "agent_judgment",
 "confidence_pass": 0.8,
 "confidence_fail": 0.4,
 "min_runs": 3
 }
}
```

## AC-Derived Requirements and Suite Graduation

Requirements with `requirement_source='ac_derived'` are derived from acceptance criteria (e.g., an AC that says "the page should be pink" generates a browser QA check). The `suite_id` field (nullable TEXT, no FK) links to a permanent test suite for test-intelligence tracking (future epic). This supports the lifecycle:

1. AC is written during spec/design
2. A browser check is derived from the AC (`requirement_source='ac_derived'`)
3. If the check proves stable, it can be graduated to a permanent suite (`suite_id` is populated)
4. Future test-intelligence tooling tracks suite membership, flakiness, and coverage

## Waivers

Any requirement can be waived by recording a `waived_at` timestamp, `waiver_rationale`, and `waiver_source`. Waived requirements are treated as satisfied for gating purposes.

**Blocking requirements require explicit authorization.** The implementation
checks the requirement's `blocking_mode`; if it is `blocking`, waiver requests
must carry force/authorization semantics. No public `yoke qa requirement
waive` adapter is registered in this branch, so this page documents waiver
semantics without teaching an operator command recipe.

The `waiver_source` field records whether the waiver was authorized by a human operator (`operator`) or an automated agent (`agent`). This provides an audit trail for blocking requirement waivers.

## Events

QA-domain writes emit unified events via `yoke_core.domain.events.emit_event` (contract):

| Event Name | When Emitted |
|------------|--------------|
| `QARequirementCreated` | New qa_requirement row inserted |
| `QARequirementWaived` | Requirement waived |
| `QARunStarted` | New qa_run row inserted (no verdict yet) |
| `QARunCompleted` | qa_run verdict recorded |
| `QAArtifactAttached` | qa_artifact row inserted |

All event names are registered in the `event_registry` table.

### Current Lifecycle Vocabulary

The current canonical status for this checkpoint is `reviewed-implementation`.
`verification` remains a QA phase name, not a lifecycle status. Retired lifecycle
names from the older QA-stage vocabulary should not appear in current runtime
code, docs, or live DB rows.

## CLI Reference

The public QA CLI supports registered `yoke qa ...` commands for requirement
CRUD, run recording/listing, artifact upload/attachment, and read-only gate
summaries. Full command shapes, argument tables, missing-adapter dispositions,
exit codes, and lifecycle environment variables (including
`YOKE_QA_GATE_BYPASS`, `YOKE_SKIP_SIMULATION`) live in
[qa-platform/cli-reference.md](qa-platform/cli-reference.md).

## Doctor Health Check

A doctor health check (HC) detects items in `reviewing-implementation` with zero `qa_requirements` rows. This catches items that entered the review lane before the guard was deployed.
