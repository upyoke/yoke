# QA Platform

Yoke's QA platform replaces the legacy `reviews` table with a unified, requirement-driven quality assurance model. Every item must carry explicit QA requirements before it can enter the review lane (`reviewing-implementation` in the current lifecycle). QA results are recorded as typed runs with non-binary verdicts, artifacts, and codified success policies. Agent writes against the QA tables route through the Yoke function-call surface (`qa.requirement.add`,
`qa.requirement.add_batch`, `qa.requirement.list`, `qa.requirement.get`, `qa.requirement.update`,
`qa.plan.materialize`, `qa.run.add`, `qa.run.complete`, `qa.run.record_verdict`, `qa.run.list`,
`qa.artifact.presign`, `qa.artifact.add`, `qa.artifact.rehome`, `qa.gate_summary.run`, `qa.browser_context.get`, and
`qa.case_execution.begin`). The public `yoke qa ...` commands (for example `yoke qa requirement list`)
are the retained operator/debug adapters that dispatch the matching function ids. See
[.yoke/docs/reference/db-reference/functions.md](db-reference/functions.md) for the envelope. Render
the operator-readable Atlas of registered surfaces locally with
`python3 -m yoke_core.tools.atlas_render_docs render`. For standalone project QA, run `yoke qa plan run --plan PLAN --project P`; read its `--help` and [standalone plan contracts](qa-platform/standalone-plans.md) before execution.

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

### Layer 2: performed_by -- How is it run?

| Value | Description |
|-------|-------------|
| `agent` | Claude agent (Tester, Simulator) executes and judges |
| `agent_mission` | Exploratory walker captures findings; the main agent judges |
| `shell` | Shell script execution (`exit_code == 0` = pass) |
| `playwright` | Playwright browser automation framework |
| `manual` | Human performs the QA step and records result |
| `github-actions` | GitHub Actions workflow execution |

### Layer 3: capability_requirements -- What runtime access is needed?

JSON array of capability slugs. Case admission checks these against the project's `project_capabilities` rows and the executing harness session, and refuses a case whose host is missing one. The one exemption is per runner, never per kind: a kind passes admission only for a case whose own `runner_id` is declared to supply it on the machine that runs the case (`browser_substrate` starts the machine-local browser daemon, which installs the runtime it needs; `agent_mission`'s dispatch contract requires the walker to run `yoke qa browser setup` on its target host before any browser step). The same kind on any other runner is still refused — a `worktree_run` or `ci_run` case declaring `browser-control` does not pass — and kinds naming project or host authority, such as `test-machine`, are exempt for no runner at all.

```json
["browser", "docker", "ssh", "repo", "github"]
```

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
deployment_stage TEXT -- nullable; pinned schema-2 QA stage on a deployment subject
deployment_member_item_id INTEGER -- nullable; attached member for item-scoped stage QA
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
superseded_by_requirement_id INTEGER -- the corrected case that answered this one
superseded_at TEXT -- ISO timestamp if superseded
supersession_rationale TEXT -- why the corrected case answers this obligation
supersession_source TEXT -- 'operator' or 'agent'
replacement_requirement_id INTEGER -- the corrected case declared to carry this failed one; supersedes it once it passes
created_at TEXT NOT NULL
```

**Polymorphic FK constraint:** Exactly one of (`item_id`), (`epic_id` + `task_num`), or (`deployment_run_id`) must be non-NULL. Deployment subjects are either legacy (`deployment_stage` and member both NULL), run-scoped (stage set, member NULL), or item-scoped (stage and member set):

```sql
CHECK (
 (item_id IS NOT NULL AND epic_id IS NULL AND task_num IS NULL AND deployment_run_id IS NULL AND deployment_stage IS NULL AND deployment_member_item_id IS NULL) OR
 (item_id IS NULL AND epic_id IS NOT NULL AND task_num IS NOT NULL AND deployment_run_id IS NULL AND deployment_stage IS NULL AND deployment_member_item_id IS NULL) OR
 (item_id IS NULL AND epic_id IS NULL AND task_num IS NULL AND deployment_run_id IS NOT NULL AND ((deployment_stage IS NULL AND deployment_member_item_id IS NULL) OR deployment_stage IS NOT NULL))
)
```

**Indexes:** See the canonical [QA schema reference](db-reference/qa-and-sessions.md) for subject indexes and scoped execution keys.

### qa_runs

Records individual QA executions against a requirement. Multiple runs per requirement support statistical success policies.

```sql
id INTEGER PRIMARY KEY
qa_requirement_id INTEGER NOT NULL -- FK to qa_requirements(id)
performed_by TEXT NOT NULL -- how it ran: agent, shell, playwright, manual, github-actions
qa_kind TEXT NOT NULL -- denormalized from requirement for query convenience
verdict TEXT -- CHECK: pass | fail | undetermined | error (nullable: started but not completed)
verdict_reason TEXT -- required when undetermined; agent outcomes also require linked evidence
score REAL -- nullable numeric score
confidence REAL -- nullable confidence level (0.0-1.0)
raw_result TEXT -- → JSONB on Postgres; JSON: full execution output; browser_substrate runs also record code_identity.branch / code_identity.sha and sign_in.profile / sign_in.authenticated
duration_ms INTEGER -- nullable execution duration
started_at TEXT -- ISO timestamp
completed_at TEXT -- ISO timestamp
created_at TEXT NOT NULL
```

**Index:** `idx_qa_runs_requirement(qa_requirement_id)`

### qa_artifacts

QA artifacts attach screenshots, diffs, logs and traces to a run. The
[QA database reference](db-reference/qa-and-sessions.md) owns their schema,
typed handles, configured storage and gate validation.

## success_policy JSON Schema

The `success_policy` column on `qa_requirements` stores a JSON object defining what counts as success. Five policy types are supported (`deterministic`, `threshold`, `statistical`, `composite`, `agent_judgment`); each has its own JSON shape, semantics, and evaluation rules. Full schema and decision logic per type live in [qa-platform/success-policy-schema.md](qa-platform/success-policy-schema.md). Downstream consumers (conduct, usher) implement policy evaluation; a centralized evaluation engine is deferred.

## QA Phases

`qa_phase` is a controlled vocabulary meaning "when in the delivery/implementation lifecycle this requirement becomes due."

| Phase | When Due | Gating Effect |
|-------|----------|---------------|
| `verification` | During conduct/tester verification, before `reviewed-implementation` | Blocks the `reviewed-implementation` transition |
| `post_deploy` | Accepted admitted copies on the selected completion run, including while settling | Blocks `done` until every copy and its stage pass for the recorded candidate and target; the source needs no separate CI verdict |
| `manual_acceptance` | After automated QA, requires human sign-off | Blocks `done` transition |

## Target Environments

`target_env` names a registered environment; an authorized name stores the canonical snapshot.

| Value | Description |
|-------|-------------|
| `local` | No Yoke environment record required |
| `preview` | Named non-production target (e.g., staging, qa, shmaging) |
| `ephemeral` | Short-lived branch/item-scoped environment |
| `prod` | Production environment |

Notes: `preview` and `ephemeral` are distinct -- one is not shorthand for the other. Concrete preview
names (staging, qa, shmaging) are preview-environment names, not separate `target_env` enum values.
Preview environments may participate in delivery-time targeting; ephemeral environments are
branch/item-scoped validation infrastructure. Not every project has every target environment, and
detailed browser-environment semantics are canonical.

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
| `seeded_default` | Auto-seeded by project/workflow policy |
| `ac_derived` | Derived from acceptance criteria (e.g., AC -> browser check) |
| `flow_derived` | Materialized from deployment flow definition |

## Gating Semantics

### Validation Entry Guard

When an item or task transitions to `reviewing-implementation`, the system checks that at least one `qa_requirements` row exists. If zero exist, the transition is rejected with a clear error message.

**Implementation:** `yoke_core.domain.qa_gates` enforces this during the lifecycle transition.
Operators inspect the public requirement read surface with `yoke qa requirement list --item PREFIX-N`.

### Review-Complete Gate

Transitioning to `reviewed-implementation` requires all blocking `verification`-phase requirements
to be "satisfied": at least one `qa_runs` row with `verdict='pass'`, or waived (`waived_at IS NOT
NULL`). **Public preview:** `yoke qa gate-summary --item PREFIX-N --target reviewed-implementation --json`

### Done Gate

`done` settles item-bound (`item_id`) and member-scoped run-bound (`deployment_member_item_id`) blocking rows, any phase; a superseded run-bound failure settles only when its passing replacement has the same run, stage, member, and execution target and that stage is accepted. Admitted copies and stage-acceptance rows settle a source or run stage rather than binding twice. The refusal names the requirement and its run. `cancelled` and `stopped` abandon without settling or auto-waiving. A member with no such rows is distinct from one whose obligation is unsatisfied.

**Public preview:** `yoke qa gate-summary --item PREFIX-N --target done --json`

Terminal settlement ignores a closed, verdict-less run only when its superseding requirement has completed passing evidence or a recorded discharge; post-deploy successors need accepted admitted copies on the completion member (run-wide copies for a legacy schema-1 run). An unsettled successor is named in the refusal. Live runs and active plan executions still block, and the old run remains unchanged as history.

### Bypass

`YOKE_QA_GATE_BYPASS=1` is accepted only in pytest contexts; production use refuses as `GATE_QA_BYPASS_FORBIDDEN`. Unset it and satisfy or explicitly waive every declared requirement.

## Requirement Materialization

### Item-Level Requirements

Issue and epic items must have materialized item-level requirements before entering the QA-gated review lane. The shepherd skill or seeded defaults attach these during item definition.

Materializing again after the plan changed converges added cases: `yoke qa plan materialize` gives every case the plan has gained its row and confirms existing rows without rewriting them. `yoke qa plan rematerialize` converges the rest in one pass: amended rows are refreshed in place, cases the plan lost are waived, and `plan_ids` names every plan the call reached — including a plan a delivery already answered, whose existing rows still come current though it gains no new row. On a deployment stage it converges case by case, so an answered sibling never blocks the rest: unjudged rows refresh, a failed case whose content changed gets one corrected row declared its replacement, and a passed case stands. A case already carried by an explicit `--replaces` declaration gets no second, automatic correction. Depth: `yoke qa plan materialize --help`, `yoke qa plan rematerialize --help`.

### Epic Task Requirements

Epic tasks may carry task-level requirements for task execution and verification. Task-level blocking requirements gate that task's `reviewed-implementation` and `done` transitions. Epic tasks mirror parent epic statuses including `release` — tasks cascade through `release` when the parent epic enters the release phase.

### Epic Parent Aggregation

An epic parent item cannot become `reviewed-implementation` until every blocking epic-task
verification requirement and every blocking epic-level requirement is satisfied.


### Deployment Run Requirements

Deployment runs materialize a named project plan as post-deploy requirements that prove release
health. Name the QA stage, and the member too when its scope is `item` — every QA stage credits only requirements carrying its own name, so a run pinning one refuses the unscoped form ([case-attachment.md](qa-platform/case-attachment.md)):

```text
yoke qa plan run \
  --deployment-run-id <run-id> \
  --stage <stage-name> [--member <PREFIX-N>] \
  --plan <plan-slug> \
  --project <project>
```

One case at a time, with no plan, is the same `qa.requirement.add` an item uses, targeted at the run instead — authoring shapes, refusals, and which cases the shared activity read returns are in [case-attachment.md](qa-platform/case-attachment.md).

The run is the durable execution subject. Materialization and execution do not create a
synthetic item: the immutable roster, serial Test Machine lease, QA runs, artifacts, and verdicts
all remain bound through `qa_requirements.deployment_run_id`. Run-scoped reads stay explicit:
`qa.plan.get` filters every case proof to the run, `qa.activity.list` returns and filters the
same field, `qa.browser_context.get` takes a `deployment_run` target and scopes its case read
to that run, and `qa.artifact.read` resolves evidence through the run's owning project.

`qa.plan.get` defaults to the scannable shape — cases, methods, target, each case's verdict. Probe source and every proof's output tail, evidence and review come back under `detail="full"` (`--full` on `yoke qa plan get`), which the summary names.

Item-scoped reads are the other half, because an item-attached requirement records no
deployment run at all: `qa.activity.list` also takes `item_ids` (absent reads the project; an
empty list matches nothing), and every row reports `item_id`, `deployment_member_item_id`,
`deployment_stage`, and `deployment_run_id`. A surface showing a known set of subjects — the
items a deployment card carries — reads their evidence rather than whatever QA is most recent,
and can tell an item's own proof from what it proved inside a release. Latest captured runs stay `captured` until reviewed; no-obligation members show their settled answer and reason in Item QA. Run Identity shows the recorded artifact identity, or explains that the run pins only a source revision. With `item_ids`, `limit`
bounds each item's checks **within each deployment run they name**, and its run-less checks as
their own group, so neither another item nor another release can take the rows a given card
needs; `deployment_run_ids` keeps the answer to the run groups a caller draws (an item's run-less
checks always travel), so it is sized by what is on screen rather than by a lifetime of releases.
`item_selection` reports `per_group_limit` with the `truncated_groups` it cut short, group by
group. What a cut-short group loses is old history, never a live request: a review names its own
item — `deployment_member_item_id` for a release's per-member check — so callers join pending
reviews through their subjects rather than through the rows a cap may have trimmed.

## Browser Methods

Browser execution is method-backed and case-scoped. The built-in methods are:

- **Browser check** (`browser-check`) — runs declared browser assertions and
  produces an automatic verdict.
- **Browser inspection** (`browser-inspection`) — captures evidence before agent
  `undetermined`, which halts for owner/operator review; an unexecuted case records `blocked_on_precondition` and fails its scheduler without human work.

Each materialized requirement carries a `method_config` snapshot. Correct a live item case with `qa.requirement.update --field method_config`; a deployment-run row accepts that write until it records a `pass` or `fail`, then refuses it as `frozen_requirement_immutable` and names supersession. Correcting an item case also reconciles the admitted copies a still-active deployment run holds of it: an unjudged copy is corrected with the source, one that has answered or that a live execution has frozen refuses as `admitted_copy_in_flight` before either row is written, and one on a terminal run is left as the acceptance record it is. A copy whose own obligation is already settled — waived, or superseded by a corrected case — is not in flight at all and holds nothing still, so it never blocks the correction the supersede receipt just named. A copy that diverges from its source anyway refuses as `admitted_case_superseded` when the roster builds and at every case begin, and `qa.requirement.list` reports each copy's `source_currency`. Case runners record the executed config and execution-target digest at run start inside `raw_result` and keep those snapshots through complete, so a prior green does not prove a later script or a later `target_env`. Human review of a capture copies that capture's recorded method_config and digest; approve fails closed when the live case is executable and the reviewed capture has no recorded method_config. An in-place method_config correction records a revision marker on the requirement; once set it stays, including through empty config, and unstamped historical greens then no longer satisfy. Plan currency compares executable configuration without that internal marker: a correction matching the plan reads as current even without a live delivery, while changed executable configuration or other plan definition fields still read as stale. A `target_env` correction persists the live snapshot instead of that marker; acceptance compares the start-bound digest. Routes, assertions, waits, and screenshots belong in the snapshot, not in `qa_kind`.

```json
{
  "method_id": "browser-check",
  "instructions": "Open the dashboard and verify its ready state.",
  "expected_outcome": "The dashboard is visible and ready.",
  "method_config": {
    "steps": [
      {"action": "navigate", "route": "/dashboard"},
      {"action": "assert", "target": "[data-ready=true]", "check": "visible"},
      {"action": "screenshot", "capture": true}
    ]
  }
}
```

Execute one materialized case at a time:

```text
yoke qa case run \
  --requirement-id <requirement-id> \
  --base-url <environment-url> \
  --expected-branch <branch> \
  --expected-sha <commit>
```

A case attached to a deployment run needs neither flag: it is judged against the commit that run was pinned to deliver, and refuses by name when the run pins none, when a different commit is named for it, or when the environment cannot prove what it serves.

`yoke qa browser setup`, `status`, `screenshot`, and `step` are machine-substrate utilities; diagnostic capture creates no parallel verdict. Saved browser profiles use the [per-OS baseline procedures](qa-platform/browser-profile-baseline.md).

## AC-Derived Requirements and Suite Graduation

Requirements with `requirement_source='ac_derived'` are derived from acceptance criteria (e.g., an AC that says "the page should be pink" generates a Browser check case). The `suite_id` field (nullable TEXT, no FK) links to a permanent test suite for test-intelligence tracking (future epic). This supports the lifecycle:

1. AC is written during spec/design
2. A Browser check case is derived from the AC (`requirement_source='ac_derived'`)
3. If stable, graduate to a suite (`suite_id`); later tooling tracks membership.

## Discharges: waiver, supersession, and retraction

For an admitted case with a `fail` or `error` verdict on a named deployment QA stage (never a passed case or one with no verdict), create a plan containing only the corrected case, then run `yoke watch qa-plan -- --deployment-run-id RUN --stage STAGE --member ITEM --plan CORRECTED_PLAN --project PROJECT --replaces CORRECTED_CASE_KEY=FAILED_REQUIREMENT_ID`. The stage accepts this correction-only plan even though its original cases are already named. Materialization and declaration commit together; the failed attempt remains history, the corrected blocking case must pass, and a still-pending sibling remains a blocker. Repeat the same command after an interrupted delivery; it reuses the declaration. If a corrected direct requirement already exists, use `yoke qa requirement supersede --requirement-id FAILED_ID --superseded-by-requirement-id CORRECTED_ID --rationale 'corrected case' --declare-replacement`, then run the scoped QA plan without `--plan`. The old case leaves the roster, and the corrected case still needs a pass.
A requirement that has not passed can still be discharged, three ways. All are recorded, all count as satisfied for gating, and all stay distinguishable from a passing result. **Waiver** records `waived_at`, `waiver_rationale`, and `waiver_source` (`operator` or `agent`), via `yoke qa requirement waive`; a `blocking` requirement needs `--force`. An operator decides a waiver. For an item or member requirement, the recorder of `--source operator` must hold its item work claim, a live steering seat covering the item (including document membership), or the deploy lock for the run holding that requirement. Another worker can keep its item claim while steering records the operator's rationale; re-drive that same run to settle its discharged stage. A deploy lock for another project or an item requirement outside the run grants nothing. Agent-sourced waivers retain the normal QA subject claim rule. Depth: `yoke qa requirement waive --help`. **Supersession** records that a corrected case answered a frozen one: the corrected case must be bound to the same deployment run, stage, member and execution target (for an item case, the same item, transition, phase and target), be blocking, and have recorded a passing verdict, and it is still graded on its own evidence, so a link cannot carry a failure through. The superseded row is left untouched as history. The normal route is a **declared replacement**: `yoke qa plan run ... --plan CORRECTED --replaces CASE_KEY=FAILED_ID` (or `yoke qa plan materialize ... --replaces`) records `replacement_requirement_id` on the failed row, which keeps blocking but leaves the execution roster, so the review bundle holds only newly captured cases; a passing independent verdict (agent review or human approval) on the corrected case supersedes it on that verdict's transaction, and a failing or undetermined one supersedes nothing. A content-refreshed corrected row declares itself automatically. `yoke qa requirement supersede` records one by hand. **Retraction** withdraws a mis-specified post-deploy item plan attachment via `yoke qa item-plan retract`: the attachment row stays as history, requirements it materialized retire as retracted (not waived, not superseded), and the item is unanswered again. Every done and member close-out reader excludes retracted requirements from obligations, including the status write used during run settlement and Browser evidence/freshness checks. Gate summaries retain those rows as `RETIRED` history with `retracted_at`, never as unsatisfied requirements. Release admission and frozen stage selection skip withdrawn requirements and member plan attachments, so a replacement active plan supplies the cases. For a frozen run that an older build already populated from a withdrawn plan, repeat `yoke qa item-plan retract --item ITEM --project PROJECT --plan-id PLAN --transition release --reason "withdraw the mis-scoped plan"`: it retires still-unretracted copies while preserving the original attachment withdrawal and refusing any passing copy. Re-drive the run or execute its member-scoped QA stage afterward; the withdrawn copy no longer blocks, and any replacement still needs its own evidence. A verification-phase attachment and a post-deploy case that already passed both refuse. Both waiver and supersession settle the obligation at every boundary that reads it — including selected Dash verification before merge and at close-out, where a superseding case needs its own current same-candidate pass (its recorded head must belong to the item's accepted revision set, including the current lane head after rework of a merged item) and an unfinished replacement is named with the evidence still owed; no manual waiver is needed — the deployment stage's acceptance check, and the item's `done` gate, which honors an admitted copy's discharge and a run-bound member case's validated same-scope supersession after stage acceptance; an un-superseded failing case still holds `done`. Supersession is run-local: it discharges one frozen copy and never reaches the item requirement an admitted copy was frozen from, because that row is a real outstanding obligation and discharging it from here would drop it forever. An outstanding source row would admit the same body again on the next release. So a supersession whose discharged row is an admitted copy returns `admitted_from_requirement_id` and a `next_admission_notice` naming that source row and the `yoke qa requirement update` command that corrects it, whenever the source is still outstanding; a source that is missing or itself already discharged is named by neither, because no future release admits it.
A deployment stage subject whose every blocking case is discharged has nothing left to execute, so it reports `discharged` rather than `accepted` — accepted for gating, named apart because an authorized discharge is not a result that passed. A carried cross-project member owes no item QA when its own completion flow declares no item-scoped QA and it has no explicit plan or post-deploy requirement; reports name that flow, no answer is recorded, and it closes with the run. Same-project members and carried members whose own flow declares item QA still owe an answer. Otherwise a subject with no materialized cases is unanswered unless the member recorded that it has no post-deploy obligation (`yoke qa post-deploy record-no-obligation`, not a waiver) or a waiver-backed declaration. Depth: `yoke qa plan run --help`.

## Events

QA-domain writes emit unified events via `yoke_core.domain.events.emit_event` (contract):

| Event Name | When Emitted |
|------------|--------------|
| `QARequirementCreated` | Every qa_requirement insert, whatever created it — an operator/function add, a materialized plan case, the merge-gate CI requirement, or the seeded no-tests floor. Paths that write the row inside a transaction their caller commits emit with `transactional=True`, so the row and its event become durable together; `HC-event-family-liveness` pairs rows with events per `requirement_source`, so one emitting path cannot mask a silent one. |
| `QARequirementWaived` | Requirement waived |
| `QARequirementRetracted` | Item plan attachment withdrawn; requirement retired as retracted |
| `QARequirementSuperseded` | Frozen requirement discharged by a corrected case that passed |
| `QARunStarted` | New qa_run row inserted (no verdict yet) |
| `QARunCompleted` | qa_run verdict recorded |
| `QAArtifactAttached` | qa_artifact row inserted |

All event names are registered in the `event_registry` table. Attach of a plan bound to the item's delivery environment at a pre-delivery transition is refused and names the post-deploy attachment that works.

### Current Lifecycle Vocabulary

`reviewed-implementation` is the checkpoint status; `verification` is a QA phase, not a lifecycle status. Retired QA-stage lifecycle names must not appear in current runtime.
