# Plan Case Currency

Materializing a QA plan case writes a *copy* of it onto a requirement row. The
only link back is `(plan_id, plan_case_key, host_baseline)`, and for a long
time nothing read that link in the edit direction — so correcting a plan
reached the plan and nothing else. A correction could read back perfectly
while the only copy that would actually run still carried the old text, and
the failure it produced looked like a product defect rather than a stale case.

Three surfaces close that, and this page is where they meet.

## An edit names the rows it did not reach

`qa.plan.edit` and `qa.plan_cases.replace` each report:

| Field | Meaning |
|---|---|
| `requirements_behind_plan` | One entry per live materialized row that no longer matches the plan |
| `requirements_behind_plan_count` | How many — `0` is the whole answer |

Each entry carries the `requirement_id`, its `case_key` and `host_baseline`,
the `state`, the `diverging_fields` that moved, and a `recovery` string naming
the exact command that reaches that row. Read it: a correction that stops at
the plan is a correction the case that actually runs never received.

## One operation brings a live row current

```text
yoke qa plan rematerialize --item <PREFIX-N> --transition <stage>
yoke qa plan rematerialize --deployment-run-id <RUN> --stage <S> [--member <PREFIX-N>]
```

It refreshes matching rows in place, retains their QA run history, creates
cases the plan has gained, and waives cases it has lost. It reaches **every**
executable column — `instructions` and `expected_outcome` included, which
`yoke qa requirement update` cannot write at all — because it rewrites the
materialization derivation whole rather than one allowlisted field.

The two subjects are not interchangeable. An item row is refreshed by its item
and transition; a row materialized onto a deployment stage is refreshed by its
run, stage and member. Each reported `recovery` names the one that fits the row
it is attached to.

## Where it refuses instead

A refresh will not move a row something else has already frozen a copy of, and
it decides that **before writing anything** — so a refused refresh leaves every
row exactly as it was. Half a refresh is the state hardest to reason about
afterwards, and it is the state that made the original defect invisible.

| Refusal | When | Recovery it names |
|---|---|---|
| `plan_execution_in_flight` | A live QA plan execution is walking a roster built from these rows | The full `yoke qa plan abort` invocation for that execution, then refresh and start the walk again |
| `admitted_copy_in_flight` | An admitted deployment-stage copy of a row is on a run that is still executing and cannot be corrected | The remedy available for that copy — see [Deployment QA Stage Execution](deployment-stage-execution.md) |
| answered deployment case | A deployment-stage row has already recorded a determinate verdict | `yoke qa requirement supersede`, because an answered case is an acceptance record |

Each refusal names a command that is actually reachable for the case that
raised it. A recovery that would answer with a usage error, or that names a
field no write surface can reach, is not a recovery.

## Reading drift without two bodies

`yoke qa requirement list` reports, for every materialized row:

| Field | Values |
|---|---|
| `plan_currency` | `current`, `stale`, `orphaned`, `unreadable` |
| `plan_diverging_fields` | The executable columns that moved, when `stale` |

`orphaned` means the plan no longer carries that case at that baseline — a
refresh waives it. `unreadable` means the plan case can no longer be
materialized at all, and the reason travels with the row rather than surfacing
later as a runner refusal.

The comparison is not a field digest. A plan case and a requirement row do not
share a shape: one `success_policy` document against the case's id plus params,
one row per host baseline against the case's array, and `method_name`,
`runner_id`, `verdict_path` and `capability_requirements` that exist on no plan
case at all. So the currency read re-runs the materialization transform to
derive what the row *should* be and diffs that against what it *is* — the same
derivation the insert and the refresh write. A row is reported stale only when
a refresh would genuinely change it.

What materialization decides for itself is excluded on purpose: `qa_phase`
comes from the attachment, and the execution target from environment
resolution or from the target a run already froze. Those differ on healthy
rows and are drift in neither direction.

## The link one level down

This page covers plan case → requirement row. The next link — requirement row →
the copy a deployment stage admitted from it — is
[Deployment QA Stage Execution](deployment-stage-execution.md), which reports
`source_currency` on the same rows. A row can be behind its plan, behind its
source, both, or neither, and each is named by the reader that owns it.
