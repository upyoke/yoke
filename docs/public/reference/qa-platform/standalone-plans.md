# Standalone Project QA Plans

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
`--continue-mission` resumes a stale-settled mission with its unchanged plan snapshot
and preserved host state. Read `yoke qa plan run --help` for the complete requirements.

## Function protocol

Source-generated plans record their exporter commit with
`yoke qa plan-cases sync --project P --plan-id N --cases-file SOURCE_EXPORT`.
The commit must be on the project's verified default branch. Once bound, a plan
requires provenance on every replacement and refuses the interactive editor;
manual one-off correction plans remain separate. Source sync against a serving
build without this field refuses before writing and names the required release.
Frozen deployment snapshots retain source provenance. A stage materializes its
frozen definitions even after the saved plan changes; a selected or refreshed
source not carried by the run's candidate refuses `qa_plan_source_candidate_mismatch`.
Sync definitions from that candidate or an ancestor, or deliver the newer source.

Standalone project QA uses `qa.plan_execution.begin` with a project-scoped
`global` target and payload `plan`, optional `source_revision`, `source_ref`,
`checkout_path`, `machine`, and `continue_mission`. Adapter:
`yoke qa plan run --plan PLAN --project P`; read its `--help` for source bindings.
State, heartbeat, advance, complete, abort, review, and machine/mission calls
retain that target and verify the execution's project and actor/session.
Responses carry `standalone_plan_id`; snapshots and proof reads carry
`standalone_execution_id`. Requirement-targeted recording verifies the same
owner, and browser context accepts a standalone `qa_requirement` target.
Standalone execution uses existing QA records and never credits item or deployment gates.

## Case environment obligations

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
recorded. An unadvanced action or recording outcome remains blocked until its
saved capture/result is reconciled; it cannot authorize action replay. Lost
custody, permission refusals and terminal executions refuse with recovery.
Use the original captured submission to reconcile recording; never reset a
host, spend another one-shot approval, or create a fresh campaign to repair a
lost reply. Actual case failures and intentional aborts keep their own outcomes.
Pause/resume needs a serving release carrying `qa.plan_execution.pause` and
`qa.plan_execution.resume`; a serving-floor refusal names the control-plane
operator who must supply it. Older heartbeat responses may contain a full
resume contract; the client needs only the accepted check-in receipt.
