# QA Platform

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [Verification](index.md) > QA platform
<!-- /yoke:breadcrumbs -->

QA requirements declare an obligation; typed runs, artifacts and success policies
record its evidence. Items need materialized requirements before entering
`reviewing-implementation`. Write through registered `yoke qa ...` adapters;
[function families](../functions/qa.md) own typed envelopes. For
standalone QA use `yoke qa plan run --plan PLAN --project P`; read its `--help`
and [standalone plans](standalone-plans.md) before execution.

## Four-Layer Model

Keep these dimensions independent; never collapse them into one enum.

| Dimension | Meaning and values |
|---|---|
| `qa_kind` | Free-form purpose: implementation_review, simulation, smoke, e2e, visual-regression, manual-acceptance; new kinds need no schema change. |
| `performed_by` | Execution: agent, agent_mission (walker captures, main agent judges), shell, playwright, manual, github-actions. |
| `capability_requirements` | JSON capability slugs checked against project capability and executing host/session authority. |
| `success_policy` | All-pass aggregation over current actual attempts; method-local measurement thresholds; [schema and decisions](success-policy.md). |

Admission exemptions are runner-specific: browser_substrate supplies its local
browser runtime; agent_mission requires walker setup on the target host before
browser steps. The same browser-control kind on worktree_run/ci_run still
refuses. Project/host authority such as test-machine has no runner exemption.

## Table Schemas

The [QA database reference](model/qa.md) owns complete
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

Use [Success policy](success-policy.md) for the stored
all-pass policy and evaluation rules; the stored success_policy is JSON.

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
target; follow [browser semantics](browser-targets.md#where-a-browser-case-runs).

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

In the implemented summary a post_deploy item source also reads satisfied once
the run answering its environment accepted its admitted copy -- the reading
done uses. A supplemental QA run (another environment of the same release)
answers as soon as its final item QA is accepted, before either run settles.
The implemented summary of an item also lists `unsettled_records` from the
done gate's own terminal-settlement check (a latest execution without a
verdict, a live host lease, an active plan execution); any entry makes it
unsatisfied, so the summary never reads satisfied while done refuses. An
item's own verdictless capture on a post_deploy source stops counting once
the completion run accepts that source's copies: the copies settle it.

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
post-deploy successors need accepted completion-member copies. Live executions/active plans still block; name the unsettled
successor. `YOKE_QA_GATE_BYPASS=1` is pytest-only; production refuses
GATE_QA_BYPASS_FORBIDDEN. Unset it and satisfy or explicitly waive obligations.

## Requirement Materialization

Item requirements are attached by definition/seeded policy before review.
At the first transition that needs them, materialize snapshots each attached
plan once for that item and transition. Later transition and merge gates read
those rows without re-deriving, inserting or rewriting them, even if cases,
environment labels or baselines change. A newly attached plan gets its own
rows. Only an explicit `yoke qa plan rematerialize` applies later plan edits:
it refreshes amended rows, creates added cases and retires removed cases.
Refresh preserves operator waivers and clears only waivers with source
`system`. It reports all plan_ids reached, including already-answered plans
(refresh without new rows). Run-scoped copies and takeover keep their own
snapshot behavior.
A delivery answers a plan only when each current case variant has a run copy
for the member that passed or was waived; a retracted copy (withdrawn from its
run, as when the member left it) or a superseded one answers nothing, so a
plan whose only copies were retracted stays owed and materializes again.
Item refresh skips shared copies on runs the item no longer belongs to;
remaining members retain their shared rows and live executions. `--plan`
filters deployment refresh only; remove it when using `--item`. A lookup
failure refuses `qa_refresh_subject_unavailable`: inspect the item attachments
or run membership, correct the selected subject, then retry. Recovery for
a stale removed-member row names no unreachable refresh command.
On an item, a removed post_deploy case replaced by exactly one created row
(same item/transition/phase/environment/baseline) is superseded by it
(superseded_requirement_ids), so the corrected case's run copies close the
item; a removed case with no single successor is waived.
Deployment convergence is per case: unjudged refreshes, changed failed gets
one declared corrected replacement, passed stands. An explicit --replaces
case gets no second automatic correction. Read both commands' --help.

Task blocking requirements gate that task's reviewed-implementation/done;
tasks mirror parent statuses including cascading release. Parent review also
requires every blocking task-verification and parent requirement satisfied.

### Deployment Run Requirements

Name the pinned QA stage and member for item scope; stages credit only their
own private cases and attached plan/source/target groups. Matching attachments
share one execution and verdict across their members; other plans and targets
remain separate. Unscoped execution is refused when a stage is pinned:

```text
yoke qa plan run --item PREFIX-N --stage {STAGE} --plan {PLAN} --project {PROJECT}
```

Run-level orchestration uses its run and stage. [Shared cursor waits](deployment-plan-execution.md#shared-plan-credit)
name the execution and owner; keep the claim and park for settlement credit or
a wake to retry your own member command.
A direct case uses qa.requirement.add targeted at
the run; [case attachment](case-attachment.md) owns authoring and
refusals. No synthetic item: immutable roster, serial Test Machine lease,
runs/artifacts/verdicts stay bound to deployment_run_id. Plan/activity/browser
context reads filter that run; artifact reads authorize its owning project.

Plan get defaults to cases/methods/target/verdicts; --full includes probe source,
output tails/evidence/reviews. Item activity can filter public_refs: absent
means project, empty means none. Rows name public_ref, member ref, stage and
run. For known cards, query those subjects, not globally recent QA. Captures
stay captured until reviewed; no-obligation Item QA names its settled reason;
Run Identity names recorded artifact or source-revision-only identity.

With public_refs alone, limit caps the total rows, newest first; item_selection
reports limit, total and truncated. With deployment_run_ids too, limit applies
per item within each named run and separately to run-less checks, which still
travel; item_selection reports per_group_limit and truncated_groups. History trimming never hides pending review: join reviews by
their item/member subject, not only capped activity rows.

## Events

QARequirementCreated emits for every requirement insert, including explicit,
materialized, merge-CI and seeded floors. Caller-committed writes emit with
transactional=True; HC-event-family-liveness checks each source, not just one
emitting path. Other registered events: QARequirementWaived, QARequirementRetracted,
QARequirementSuperseded, QARunStarted, QARunCompleted, QAArtifactAttached. Attaching
a delivery-environment plan before delivery refuses and names the post-deploy
attachment. See [event/database reference](../operations/model/events.md).

## Blocking QA holds the succeeded stamp

A run does not reach `status='succeeded'` while any blocking QA obligation is
unresolved. `deployment_runs.cmd_update` is the boundary that enforces it, so
every route into a succeeded stamp — the pipeline's own finalization included —
is covered by one check. Two tables carry those obligations, and both are read:

- `deployment_run_qa`, the flow-derived checks. Only `passed` and `waived`
  resolve one; `failed` does not, being the strongest reason not to call the
  run succeeded.
- `qa_requirements` rows keyed by `deployment_run_id`, the run's plan cases. One
  resolves on a `qa_runs` row with `verdict='pass'`, or on being settled without
  evidence — waived, or superseded by a replacement graded on its own evidence.
  That rule is shared with the stage acceptance check, so the end of a release
  never re-opens what a stage already accepted. A case whose latest run is
  `undetermined` and awaits human review is named with it and its authorities.
  The item `done` gate uses each requirement's newest execution for settlement and code identity; older attempts never block. Browser reviews use the capture's verdict and identity, excluding detached agent verdict rows. A latest closed, verdict-less execution on a superseded requirement stops blocking only after its successor passes or is discharged (post-deploy proof needs accepted completion-member copies, and those accepted copies also settle the item's own verdictless capture on that source). Refusals name unsettled successors; latest live executions and active plans still block. The gate also reads the same rows when they name the item as
  `deployment_member_public_ref`; run-scoped rows with no member stay the run's.

Non-blocking checks never hold a run, and `force=True` overrides the
hold exactly as it overrides the stage checks beside it.

## Related

- [Requirement discharges](requirement-discharges.md)
- [QA model](model/qa.md)
- [Browser targets](browser-targets.md)
