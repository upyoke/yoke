# Standalone Project QA Plans

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Verification](index.md) > Standalone plans
<!-- /yoke:breadcrumbs -->

Run a saved plan immediately without an item or deployment run:

```text
yoke qa plan run --plan PLAN --project P
```

Each fresh run freezes cases and host baselines in saved order in existing QA
execution, requirement, run, review, and artifact records. Its standalone execution
owns the evidence and changes no item transition, delivery acceptance, or stage gate.
An interrupted live run resumes its immutable roster and cursor in its owning session.
Latest-execution reads select the unique live owner first, then the greatest
database-assigned execution order. Requirement creation, timestamp precision,
and random execution ids do not determine that order. The identity column is
added on boot to existing databases; historical rows receive an order at that
convergence, which cannot recover their original same-second creation order.
Unsupported runners or missing capabilities refuse before any case executes.

Commands require `--checkout-path PATH --expected-sha FULL_SHA`: the checkout
must be clean at that commit. CI cases require the SHA and `--expected-branch REF`,
a published branch or tag at that commit, and a case-declared `ci_workflow`.
They dispatch with declared `ci_workflow_inputs`, verify the run's actual commit,
and record its URL and conclusion. Manual CI does not publish, rebase, or open a
landing PR, including on merge-queue projects.

Browser, terminal, machine-state, inspection, and exploratory cases retain their
target, capability, serial lease, evidence, and review contracts.
Read proof with `yoke qa plan get PLAN --project P --full`, then inspect returned
requirement and run ids through QA reads. Abort with
`yoke qa plan abort --project P --execution-id ID --reason TEXT`.
An in-flight host abort retains custody until the runner records case cleanup;
only a declared baseline requires restoration. An `as_is` case or chain without
a baseline settles on its no-restore cleanup receipt. Follow
[safe host cancellation](deployment-plan-execution.md#stop-host-work-safely)
when it returns `qa_abort_restore_pending`.
`--continue-mission` resumes a stale-settled mission with its unchanged plan snapshot
and preserved host state. Continuation commands omit `--test-machine`; the scheduler
keeps simultaneous cases on their declared driver and full host set. For
single-host cases it recovers each platform’s original host from durable leases and runs, and selects
a fresh eligible host only for a platform not used before. Read `yoke qa plan run --help` for
the complete requirements.

## Function protocol

Source-generated plans record their exporter commit with
`yoke qa plan-cases sync --project P --plan-id N --cases-file SOURCE_EXPORT`.
The commit must be on the project's verified default branch. A source-bound
plan whose cases the Yoke build itself generates also converges when a server
running that build boots, moving forward to the build commit; every other
source-bound plan moves only through sync. Once bound, a plan
requires provenance on every replacement and refuses the interactive editor;
manual one-off correction plans remain separate. Source sync against a serving
build without this field refuses before writing and names the required release.
Frozen deployment snapshots retain source provenance. A stage materializes its
frozen definitions even after the saved plan changes; a selected or refreshed
source not carried by the run's candidate refuses `qa_plan_source_candidate_mismatch`.
Release a candidate carrying the newer source, or use a run-bound correction.
A plan the run froze while unbound keeps its frozen cases for that run after a
later sync binds it; its stages, retraction and retirement proceed. A snapshot
with no source field at all refuses `qa_plan_source_snapshot_missing`.
A sync moves only forward: its revision must equal or descend from the plan's
recorded revision. An older revision refuses `qa_plan_source_revision_regression`
and an unprovable recorded revision refuses `qa_plan_source_ancestry_unverified`;
both name the two revisions and write nothing. Export from current main and sync again.

Standalone project QA uses `qa.plan_execution.begin` with a project-scoped
`global` target and payload `plan`, optional `source_revision`, `source_ref`,
`checkout_path`, `test_machine`, and `continue_mission`. Adapter:
`yoke qa plan run --plan PLAN --project P`; read its `--help` for source bindings.
State, heartbeat, advance, complete, abort, review, and machine/mission calls
retain that target and verify the execution's project and actor/session.
Responses carry `standalone_plan_id`; snapshots and proof reads carry
`standalone_execution_id`. Requirement-targeted recording verifies the same
owner, and browser context accepts a standalone `qa_requirement` target.
Standalone execution uses existing QA records and never credits item or deployment gates.

## Case environment obligations

Every case is [self-contained](case-attachment.md#self-contained-cases): it
never relies on the runner's seat, claim or session.


A case can declare `"target_envs": ["prod"]` in the JSON supplied to
`yoke qa plan-cases replace` or `yoke qa plan edit`. These are unique registered
environment names on the plan's project, each with a reviewable URL. Use `[]`
to keep the plan's default target. `qa plan edit` puts every case field in its
document, `target_envs` and `stage_reason` included; a save that leaves out a
field of an existing case and would reset its stored value is refused as
`qa_plan_edit_unedited_field_changed`, naming each case and field.

Verify on production by default. A case may name an environment that does not
declare `role.production: true` (stage) only when the check cannot safely run
on production, and must say why in `stage_reason`:

| `stage_reason` | When |
|---|---|
| `creates_or_destroys_data` | The check creates or destroys real data, such as founding a tenant or approving a fresh-install machine |
| `changes_infrastructure` | The check changes infrastructure, such as renewing a TLS certificate |

```json
{"case_key": "new-founder-tenant", "target_envs": ["stage"], "stage_reason": "creates_or_destroys_data"}
```

A stage target without a reason refuses as `stage_reason_required`; retarget a
read-only check to production. An unknown value refuses as
`stage_reason_invalid`, and a reason on a case with no stage target refuses as
`stage_reason_without_stage_target`. Declare the production environment with
`yoke projects environment-settings merge --project P --environment prod --set role.production=true`.

When the plan's project declares `qa.restrict_execution_to_self: true` on the
environment the control plane runs as, that control plane runs only QA that
targets its own environment; Yoke's hosted Stage and Production declare it. There,
a standalone `yoke qa plan run` whose case targets another environment refuses
with `cannot execute QA target`. Run the plan from the target environment's own
control plane (select its connection with `yoke --env NAME`), or prove the case
through a deployment QA stage that targets that environment. Without the
setting, a control plane may run a plan against any registered environment.
`stage_reason` governs a case's `target_envs` only: a plan created with
`--environment stage` needs none, but still runs only where that environment's
QA may execute.

Item materialization creates one requirement per environment and host baseline,
with `target_env` and an immutable execution target on each row. Rematerializing
keeps matching case key, baseline, and environment identities, and waives only
variants removed from the definition. Deployment stages materialize only cases
applicable to their own target; evidence from Production cannot prove Stage.

Attach delivery cases at the workflow's release transition with
`--qa-phase post_deploy`, then materialize them before release composition so
Stage-targeted obligations enroll the item on a matching supplemental run.
The item stays at its release wait until every blocking target is accepted.
`missing_target_proof` names the missing environment and matching active flows;
if no flow can carry it, configure an item QA stage for that environment and
deliver the same candidate through it. Use target-relative commands such as
`BASE_URL` rather than hardcoded Stage or Production endpoints in shared cases.

A standalone execution has one immutable target. A plan requiring other
environments refuses with `qa_plan_requires_environment_scopes` before writing
cases. Use each item requirement or matching deployment QA stage to collect
those separate proofs; a standalone plan run never completes an item gate.
## Cases that wait for real traffic

Some checks can only be judged once real production traffic has happened after
a deploy, such as "a real failed direct wake that a relay then claimed". Run at
stage entry, they fail or prove nothing. Give such a case
`"wake_path": "manual"` and a one-line `wake_evidence`:

```json
{"case_key": "relay-claim-observation", "method_id": "exploratory-mission", "wake_path": "manual", "wake_evidence": "a session wake that failed directly and a relay then claimed exists after this release"}
```

| `wake_path` | Starts |
|---|---|
| `automatic` (default) | When its stage begins: the stage driver wakes the member's owner |
| `manual` | Once its owner confirms `wake_evidence`: the stage driver wakes the owner to check it |

Write `wake_evidence` as the evidence itself, as something a registered read
can confirm (`yoke deployment-runs get`, `yoke db read`, `yoke qa requirement
list`), not as a time or a hope. Method, runner and verdict path are
unchanged, and the case stays blocking until it is settled, waived or removed.
`manual` without evidence refuses `wake_evidence_required`; evidence on an
automatic case refuses `wake_evidence_without_manual_wake`; an unknown path
refuses `wake_path_invalid`; more than one line or 300 characters refuses
`wake_evidence_not_one_line`.

While one of a member's manual cases is open, the stage driver sends its
owner one notice per open manual case instead of the ordinary stage wake,
because one stage execution runs the member's whole roster. The notice names
the evidence: check it with a registered read, run the member's cases if it
exists, otherwise ask the operator through `yoke say --steering` to waive or
remove the case. A parked holder is woken; a member with no live holder
reaches the project's steering seat. The steering fleet report lists each open
one under "waiting on manual wake" with its run, item, requirement, case,
evidence, owner and run command. To mark an already materialized requirement,
set the evidence first, then the path:

```text
yoke qa requirement update --requirement-id N --field wake_evidence --value '<evidence>'
yoke qa requirement update --requirement-id N --field wake_path --value manual
```

The write reaches only that row. Correct the plan case as well, so later
materializations carry it.



## Recover a lost check-in response

```text
yoke qa plan run --plan PLAN --project P --resume-execution-id EXECUTION_ID
```

Keep the original source and machine arguments. A response timeout leaves the
action's outcome unknown: it does not cancel a server success. The check-in
retries once with its exact request id, allowing the existing request ledger
to replay a late success. It returns only cursor, target/roster identity,
custody and liveness timing; it does not rebuild a full resume response.

If communication stays unavailable, `outcome_unknown` names the execution,
phase, request, attempts and saved request evidence. A confirmed pause keeps
its cursor, results and machine leases; it does not renew them. When the pause
cannot be confirmed, preserve the command capture and last known custody.
Park the owning session with `yoke sessions touch --mode parked --reason
"QA communication pause"` while restoring communication. When a pause was
unconfirmed, add the returned `--recovery-file PATH` to exact-ID re-entry: it
reapplies only that saved pre-case check-in pause. A consumed receipt or changed
cursor refuses; inspect the current outcome instead of reusing an old receipt.

Exact-ID re-entry validates the actor/session, subject, frozen source/target
and live host custody before another case can start. Completed cases stay
recorded. A lost heartbeat during cleanup stays in the capture and does not
block case result submission. If submission also loses its response,
`outcome_unknown` preserves that request and its result payload for inspection.
An unadvanced action or recording outcome refuses automatic re-entry: keep
the saved result and request evidence and ask the control-plane operator to
inspect the durable cursor. No command replays an unrecorded case submission.
Lost custody, permission refusals and terminal executions refuse with recovery.
Never reset a host, spend another one-shot approval, or create a fresh campaign
to repair a lost reply. Actual case failures and intentional aborts keep their own outcomes.
Pause/resume needs a serving release carrying `qa.plan_execution.pause` and
`qa.plan_execution.resume`; a serving-floor refusal names the control-plane
operator who must supply it. Older heartbeat responses may contain a full
resume contract; the client needs only the accepted check-in receipt.

## Retire a plan

```text
yoke qa plan retire PLAN --project P --reason "why the plan is retired"
```

Retire a plan when it should stop answering new work: its cases are wrong or
unrunnable and no item still needs it. Run the command from a session holding
a live steering seat covering the plan's project; any other caller refuses with
`steering_seat_required` and the seat recipe. `PLAN` is the slug or numeric id.

Retirement records `retired_at`, the reason and the acting actor on the plan.
The plan stays readable: `yoke qa plan get PLAN --project P` shows the
retirement (a case whose recorded correction history is broken shows outcome
`replacement_graph_invalid` with its named repair, retired or not), and
`yoke qa plan list --project P --include-retired` lists retired
plans beside active ones. Recorded requirements, runs and reviews keep their
evidence. From then on the plan refuses edits and materialization. There is no
un-retire; author a corrected plan with `yoke qa plan create`.

While anything still depends on the plan, retirement refuses with
`qa_plan_retire_dependents` and names each dependent with the command that
settles it:

| Dependent | Settle it with |
|---|---|
| Unsettled item requirement, not yet executed | `yoke qa item-plan retract` |
| Unsettled requirement with a failed or missing latest attempt | `yoke qa requirement waive` or `supersede` |
| In-flight execution whose roster reaches the plan | let it finish, or `yoke qa plan abort` |
| Project default that attaches the plan to new items | `yoke qa project-default unset` |

A requirement whose newest attempt passed does not hold the plan, and neither
does a copy on a finished item: nothing can run it again, and a finished item
cannot be claimed to retract it. Retirement retracts those unexecuted copies,
and the attachment behind them, in the same transaction with the rationale
`QA plan retired: <reason>`, and returns their ids in
`retracted_requirement_ids`. Executed copies stay as recorded history. Repeating
retirement on a retired plan returns the recorded retirement unchanged with
`already_retired: true`, so a retry after a lost reply is safe. The command
needs a serving release carrying `qa.plan.retire`; an older server refuses with
the serving floor named.

## Related

- [Verification](index.md)
- [QA platform](platform.md)
