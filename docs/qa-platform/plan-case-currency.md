# Plan Case Currency

Materialization copies executable plan fields onto a requirement, linked by
`(plan_id, plan_case_key, host_baseline)`. Inheriting machine cases retain their
chain's initial baseline position. Copied `starting_state` and reason are compared
like other fields; a pre-declaration row may be behind its current plan.

## Edit receipts and reads

`qa.plan.edit` / `qa.plan_cases.replace` report `requirements_behind_plan` and
`requirements_behind_plan_count`. Each live divergent row names requirement id,
case key, baseline, state, diverging fields and its exact recovery. A plan edit
alone does not update the case that executes.

`yoke qa requirement list` reports materialized row currency:

| Field/value | Meaning |
|---|---|
| `plan_currency=current` | Row matches the materialization derivation. |
| `stale` | Executable fields differ; `plan_diverging_fields` names them. |
| `orphaned` | Case/baseline no longer exists; refresh waives it. |
| `unreadable` | Current case cannot materialize; the row carries its reason. |

Currency re-runs the same transformation used by insert/refresh, not a raw field
digest. Plan policy documents versus row policy id/params, baseline arrays versus
rows, and derived method/runner/verdict/capability fields have different shapes.
Only a refresh that would change the derived executable row reports stale.
Attachment-owned `qa_phase` and resolved/frozen execution targets are excluded:
those differences are healthy and do not repoint a row.

## Refresh the correct subject

```text
yoke qa plan rematerialize --item PREFIX-N --transition STAGE
yoke qa plan rematerialize --deployment-run-id RUN --stage STAGE [--member PREFIX-N]
```

The operation refreshes matching live rows in place, preserves QA run history,
creates added cases and waives removed ones. It reaches all executable columns,
including `instructions` / `expected_outcome`, which individual requirement
update cannot write. It also corrects reachable unjudged admitted deployment
copies and reports `corrected_admitted_copy_ids`.

Item rows use item/transition; stage rows use run/stage/member. These subjects
are not interchangeable. Follow each receipt's exact recovery.
All-or-nothing refusal precedes writes:

| Refusal/condition | Recovery |
|---|---|
| `plan_execution_in_flight` | Abort the named live execution with its complete `yoke qa plan abort` command, refresh, then restart. |
| `admitted_copy_in_flight` | A live roster or determinate answer froze the copy; use [deployment-stage correction](deployment-stage-execution.md). |
| Answered deployment case | `yoke qa requirement supersede`; an acceptance result is immutable. |
| Declaration-corrected target | `yoke qa requirement rebind-target` when environment/subject and resolved host authority remain the same; [rebind rules](execution-target-declaration-rebind.md) also cover stale identity labels with already-matching endpoints. A repointed host is a different target; live item requirements cannot be superseded. |

Each refusal must name the reachable remedy for that specific row, not a field
or subject its write API cannot address.

## Execution refuses superseded bodies

- Item plan-run roster construction and each machine step compare against the
  live plan; an amended case refuses as `plan_case_superseded`.
- Deployment-stage rows compare against their stage snapshot. Admission-pinned
  cases ignore later plan edits. Walk-time plan selection re-reads the plan:
  changed unjudged rows refuse; failed/discharged cases can be re-minted beside
  their historical rows under the replacement rules.
- An admitted copy whose source row moved refuses at the next source link too.

Follow the named refresh, then restart. Historical acceptance is never rewritten
or quietly credited to the changed case.

## Stored plan convergence

Authoring validates every write, but older stored plans may fail a tightened
contract during materialization. `HC-qa-plan-machine-starting-state` checks each
live machine-run plan through that same derivation and reports every refusal.
A tightened contract must converge stored plans in every universe, through
registered authoring, in the same release.

```text
yoke qa plan edit PLAN_SLUG --project P
yoke qa plan get PLAN --project P --full --json
yoke qa plan-cases replace --project P --plan-id {plan_id} --stdin
```

Reads include `starting_state` / `starting_state_reason`; preserve unchanged
declarations when writing the corrected array. The next link, requirement to
admitted stage copy, reports `source_currency` in
[Deployment QA Stage Execution](deployment-stage-execution.md). Plan/source
currency are separate: a row may be behind either, both or neither.
