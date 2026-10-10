# QA Platform

QA requirements declare an obligation; typed runs, artifacts and success policies
record its evidence. Items need materialized requirements before entering
`reviewing-implementation`. Write through registered `yoke qa ...` adapters;
[function families](db-reference/functions-qa.md) own typed envelopes. For
standalone QA use `yoke qa plan run --plan PLAN --project P`; read its `--help`
and [standalone plans](qa-platform/standalone-plans.md) before execution.

## Four-Layer Model

Keep these dimensions independent; never collapse them into one enum.

| Dimension | Meaning and values |
|---|---|
| `qa_kind` | Free-form purpose: implementation_review, simulation, smoke, e2e, visual-regression, manual-acceptance; new kinds need no schema change. |
| `performed_by` | Execution: agent, agent_mission (walker captures, main agent judges), shell, playwright, manual, github-actions. |
| `capability_requirements` | JSON capability slugs checked against project capability and executing host/session authority. |
| `success_policy` | All-pass aggregation over current actual attempts; method-local measurement thresholds; [schema and decisions](qa-platform/success-policy-schema.md). |

Admission exemptions are runner-specific: browser_substrate supplies its local
browser runtime; agent_mission requires walker setup on the target host before
browser steps. The same browser-control kind on worktree_run/ci_run still
refuses. Project/host authority such as test-machine has no runner exemption.

## Table Schemas

The [QA database reference](db-reference/qa-and-sessions.md) owns complete
qa_requirements/qa_runs/qa_artifacts schemas, indexes, typed artifact handles,
configured storage and gate validation. Requirements have exactly one subject:
item_id; epic_id + task_num; or deployment_run_id. Item/task subjects carry no
deployment stage/member; deployment subjects are legacy unscoped, run-scoped
(stage), or item-scoped (stage + member). Never substitute an item for a run.

Runs reference their requirement. Preserve pass/fail/undetermined/error and a
nullable verdict while executing; undetermined requires a reason, and agent
outcomes require evidence. Multiple attempts, raw result, score/confidence,
duration and timestamps remain history. Artifacts hold screenshots/logs/traces.
Browser captures retain code identity and authenticated sign-in evidence.

## success_policy JSON Schema

Use [success-policy-schema.md](qa-platform/success-policy-schema.md) for the five
policy shapes and evaluation rules; the stored success_policy is JSON.

## QA Phases

| Phase | Obligation |
|---|---|
| verification | Blocking requirements gate reviewed-implementation. |
| post_deploy | Accepted admitted copies on the selected completion run, including settling, must prove its candidate/stage/member/target; source needs no separate CI verdict. |
| manual_acceptance | Human sign-off gates done. |

`reviewed-implementation` is a status; `verification` is a phase. Use current
pinned lifecycle vocabulary, not retired QA-stage statuses.

## Target Environments

target_env names a registered environment and stores its authorized canonical
snapshot. `local` needs no Yoke environment; `preview` is named non-production
(staging, qa, shmaging); `ephemeral` is short-lived branch/item validation;
`prod` is production. Preview and ephemeral are distinct. Concrete preview
names are environment names, not new enum values. Projects need not have every
target; follow [browser semantics](browser-scenarios.md).

## Blocking Modes and Requirement Sources

blocking prevents transition when unsatisfied; non_blocking records evidence
without gating. requirement_source is explicit, seeded_default, ac_derived or
flow_derived. Do not infer satisfaction from source or kind.

## Gating Semantics

Entering reviewing-implementation requires at least one requirement. All
blocking verification requirements must satisfy the review-complete gate.
Inspect actual requirements and native previews:

```text
yoke qa requirement list --item PREFIX-N
yoke qa gate-summary --item PREFIX-N --target reviewed-implementation --json
yoke qa gate-summary --item PREFIX-N --target implemented --json
```

Done settles blocking item and run-member requirements of any phase. A
run-bound supersession needs the same run/stage/member/target and accepted
stage. Admitted copies and acceptance rows answer their source/stage once,
not twice. Refusals name the requirement/run. cancelled/stopped abandon;
they do not settle or auto-waive. No obligation differs from unsatisfied QA.

Newest actual execution controls settlement and identity; older attempts stay
history. Requirement-filtered run list puts the native-selected attempt first;
aware start instant precedes equal-start id ties, and detached verdict reviews
are excluded. case_outcome projects judged outcome without rewriting capture
outcome/raw evidence/timestamps. Browser review judges its capture identity.
Closed verdict-less superseded executions need a passed/discharged successor;
post-deploy successors need accepted completion-member copies (run-wide for
legacy schema-1). Live executions/active plans still block; name the unsettled
successor. `YOKE_QA_GATE_BYPASS=1` is pytest-only; production refuses
GATE_QA_BYPASS_FORBIDDEN. Unset it and satisfy or explicitly waive obligations.

## Requirement Materialization

Item requirements are attached by definition/seeded policy before review.
materialize converges newly added cases and confirms existing rows unchanged.
rematerialize refreshes amended rows, waives removed cases, and reports all
plan_ids reached, including already-answered plans (refresh without new rows).
Deployment convergence is per case: unjudged refreshes, changed failed gets
one declared corrected replacement, passed stands. An explicit --replaces
case gets no second automatic correction. Read both commands' --help.

Task blocking requirements gate that task's reviewed-implementation/done;
tasks mirror parent statuses including cascading release. Parent review also
requires every blocking task-verification and parent requirement satisfied.

### Deployment Run Requirements

Name the pinned QA stage and member for item scope; stages credit only their
own requirements and refuse unscoped execution when a stage is pinned:

```text
yoke qa plan run --deployment-run-id {RUN_ID} --stage {STAGE} --member PREFIX-N --plan {PLAN} --project {PROJECT}
```

Run scope omits --member. A direct case uses qa.requirement.add targeted at
the run; [case attachment](qa-platform/case-attachment.md) owns authoring and
refusals. No synthetic item: immutable roster, serial Test Machine lease,
runs/artifacts/verdicts stay bound to deployment_run_id. Plan/activity/browser
context reads filter that run; artifact reads authorize its owning project.

Plan get defaults to cases/methods/target/verdicts; --full includes probe source,
output tails/evidence/reviews. Item activity can filter public_refs: absent
means project, empty means none. Rows name public_ref, member ref, stage and
run. For known cards, query those subjects, not globally recent QA. Captures
stay captured until reviewed; no-obligation Item QA names its settled reason;
Run Identity names recorded artifact or source-revision-only identity.

With public_refs, limit applies per item within each named deployment run and
separately to run-less checks. deployment_run_ids limits displayed run groups;
run-less item checks still travel. item_selection reports per_group_limit and
truncated_groups. History trimming never hides pending review: join reviews by
their item/member subject, not only capped activity rows.

## Browser Methods

browser-check executes assertions and automatic verdict; browser-inspection
captures evidence for review. undetermined halts for owner/operator review.
An unexecuted precondition failure records blocked_on_precondition, fails its
scheduler, and creates no human work. Each requirement snapshots method_config;
routes/assertions/waits/screenshots belong there, not in qa_kind.

Correct an item config with qa.requirement.update --field method_config. A
deployment row freezes after pass/fail and refuses frozen_requirement_immutable
with supersession recovery. Item correction reconciles active admitted copies
(source-key/direct or matching plan/case/member/baseline/environment): unjudged
copies update atomically; answered/live-frozen copies refuse admitted_copy_in_flight
before either write. Terminal-run copies remain acceptance history. Already
waived/superseded copies are settled and cannot block correction.
A scope change (target_env, qa_phase, workflow_transition_id, blocking_mode)
or rebind-target that would break a replacement link refuses
replacement_link_scope_changed before writing; see
[requirement state model](qa-platform/requirement-state-model.md#links-that-stop-answering-for-their-obligation).

Copies execute their admitted definitions despite source drift. source_currency
diagnoses correction/refresh/new admission; drift alone never invalidates frozen
proof. At run start, raw_result records executed config and target digest,
retained through completion/review. A prior green proves neither later script
nor later target. Approval fails closed for executable captures lacking config.
In-place correction sets a persistent revision marker, even through empty config;
unstamped historic greens then fail. Plan currency compares executable config
without that marker; target_env correction stores the snapshot and acceptance
compares its start-bound digest.

Protected merge-queue CI receipts remain current for unchanged landing/config/
target even when old runners lacked start snapshots. Conflicting snapshots,
different landing or later failed/pending actual attempt still block. Matching
accepted admitted copies answer post-deploy sources for delivered candidate,
stage/member/environment through source-key or plan-case identity; no extra
source run/manual supersession. Failed/pending/mismatched copies still hold.

```json
{
  "method_id": "browser-check",
  "instructions": "Open the dashboard and verify its ready state.",
  "expected_outcome": "The dashboard is visible and ready.",
  "method_config": {
    "color_scheme": "light",
    "steps": [
      {"action": "navigate", "route": "/dashboard"},
      {"action": "assert", "target": "[data-ready=true]", "check": "visible"},
      {"action": "screenshot", "capture": true}
    ]
  }
}
```

Owned pages may declare light/dark. Runs/captures record requested and observed
media preference; missing/mismatched observation fails. Omission keeps ordinary
preference; use separate cases for both, then judge product appearance.
See [method configuration](browser-scenarios.md#method-configuration).

```text
yoke qa case run --requirement-id {REQUIREMENT_ID} --base-url {ENVIRONMENT_URL} --expected-branch {BRANCH} --expected-sha {COMMIT}
```

Deployment cases derive their own project's delivered commit: verified hosted
promotion attempt (including no-op), otherwise last release output then bound
commit. No supplied identity flags are needed. Missing/mismatched hosted
promotion, no delivered commit, conflicting supplied commit or unprovable served
environment refuses by name. Browser setup/status/screenshot/step are substrate
utilities; diagnostic captures create no parallel verdict. Use
[browser sign-in identities](qa-platform/browser-identities.md).

## AC-Derived Requirements and Suite Graduation

ac_derived records an AC-derived case. Nullable suite_id links future stable
suite membership: define AC, derive case, graduate a stable case to a suite.
The metadata itself is no passing result.

## Discharges: waiver, supersession, and retraction

Discharge is recorded and satisfies gates, while staying distinguishable from
pass. Failed/error admitted cases on a named stage can be corrected (never a
passed/no-verdict case): author only the corrected case and execute:

```text
yoke watch qa-plan -- --deployment-run-id {RUN_ID} --stage {STAGE} --member PREFIX-N --plan {CORRECTED_PLAN} --project {PROJECT} --replaces {CASE_KEY}={FAILED_REQUIREMENT_ID}
```

Materialization/declaration commit together; old failure remains history,
corrected blocking case and pending siblings still need proof. Interrupted
re-entry reuses declaration. Existing direct correction can be declared with
qa.requirement.supersede --declare-replacement, then scoped plan execution
without --plan. Predecessor leaves roster; successor still must pass.

**Waiver:** qa.requirement.waive stores waived_at/rationale/source; blocking
needs --force. Operator decides. Recording --source operator for item/member
needs its item claim, a covering steering seat (including document membership),
or the live driver of the run holding it. Steering can record the rationale while
worker keeps item custody; re-drive that run. Another run's driver or an unrelated
item grants nothing. Agent waivers keep normal QA subject-claim authority.
Read `yoke qa requirement waive --help`.

**Supersession:** corrected blocking case needs same run/stage/member/target
(item: same item/transition/phase/target) and its own qualifying pass. History
is untouched. Declared replacement via plan run/materialize --replaces records
replacement_requirement_id after same-scope/acyclic validation. Predecessor
immediately leaves grading/roster; only terminal successor answers, even pending
or failing. Review bundle includes newly captured cases only. Independent pass
(agent review or human approval) supersedes in that verdict transaction; fail/
undetermined supersedes nothing. Content refresh declares correction automatically;
qa.requirement.supersede can declare one explicitly.

**Retraction:** qa.item-plan.retract withdraws a mis-specified post-deploy item
attachment; retain attachment/requirements as retracted history, not waiver or
supersession. Item becomes unanswered. Done/member/freshness readers exclude
withdrawn obligations; summaries keep RETIRED/retracted_at history. Admission
and frozen selection skip withdrawn attachments; replacement plan owes proof.
For older frozen copies, repeat with item/project/plan-id/transition release/
reason: retires remaining copies, preserves original withdrawal, refuses any
passed copy. Re-drive scoped QA/run. Verification attachments and passed
post-deploy cases refuse retraction.

Waiver/supersession answer every gate, including Dash verification/close-out.
Supersession still needs current same-candidate pass within accepted revisions
(including current reworked lane head); unfinished successor names owed evidence.
Deployment acceptance and done honor admitted discharge and validated same-scope
member supersession after stage acceptance. Unsettled failures keep done blocked.

Run-local supersession never retires its item source: an outstanding source
would be admitted again. Receipts name admitted_from_requirement_id and
next_admission_notice only while that source is outstanding; absent/discharged
sources get neither. Retiring a post_deploy item source is explicit:

```text
yoke qa requirement add --item PREFIX-N --target-env {ENVIRONMENT} --method-id {METHOD_ID} --qa-phase post_deploy --blocking-mode blocking --workflow-transition {TRANSITION} --instructions-file {INSTRUCTIONS_FILE} --expected-outcome-file {EXPECTED_OUTCOME_FILE} --method-config '{METHOD_CONFIG_JSON}'
yoke qa requirement supersede --requirement-id {SOURCE_ID} --superseded-by-requirement-id {CORRECTED_ID} --rationale "corrected source definition"
```

Declare the corrected body through requirement-add's --help contract for the
same item/transition/phase/resolved environment; snapshot digest may differ.
Neither source executes. Instead require an admitted source copy replaced or
superseded through a chain whose terminal case has a current config/target-qualified
pass. Receipt names run_replacement_requirement_id. That case still answers its
run; corrected source reads retired source's admitted copies at done. Later
admissions skip superseded source and admit corrected one; source is never
rewritten. Control plane may record an authorized target it cannot execute
(prod recording stage); execution alone checks runtime observation authority.

All blocking cases discharged → subject reports discharged, accepted for gating
but distinct from accepted passing proof. A carried cross-project member owes
no item QA only when its own completion flow declares none and no explicit
plan/post-deploy requirement exists; report names that flow, records no answer
and closes with run. Same-project/QA-owning carried members still owe proof.
No cases otherwise means unanswered, except recorded no-post-deploy-obligation
or waiver-backed declaration. `yoke qa post-deploy record-no-obligation` is not
a waiver. Read `yoke qa plan run --help`.

## Events

QARequirementCreated emits for every requirement insert, including explicit,
materialized, merge-CI and seeded floors. Caller-committed writes emit with
transactional=True; HC-event-family-liveness checks each source, not just one
emitting path. Other registered events: QARequirementWaived, QARequirementRetracted,
QARequirementSuperseded, QARunStarted, QARunCompleted, QAArtifactAttached. Attaching
a delivery-environment plan before delivery refuses and names the post-deploy
attachment. See [event/database reference](db-reference/events-and-deployments.md).
