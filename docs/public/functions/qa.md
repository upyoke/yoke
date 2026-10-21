# QA Function Catalog

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [Functions](index.md) > QA
<!-- /yoke:breadcrumbs -->

Read [envelope and authority](index.md) first. `none` means no dispatcher work-claim check; handler permissions still apply. Read command help for the live payload and serving floor.

## Registered functions

| Function id | Claim policy |
|---|---|
| `qa.activity.list` | `none` |
| `qa.artifact.add` | `qa_subject` |
| `qa.artifact.get` | `none` |
| `qa.artifact.presign` | `qa_subject` |
| `qa.artifact.read` | `none` |
| `qa.artifact.rehome` | `qa_subject` |
| `qa.browser_context.get` | `none` |
| `qa.case.waive` | `none` |
| `qa.case_execution.begin` | `qa_subject` |
| `qa.gate_summary.run` | `none` |
| `qa.item_plan.attach` | `item` |
| `qa.item_plan.retract` | `item` |
| `qa.method.get` | `none` |
| `qa.method.list` | `none` |
| `qa.no_tests.attest` | `none` |
| `qa.no_tests.clear` | `none` |
| `qa.plan.create` | `none` |
| `qa.plan.edit` | `none` |
| `qa.plan.get` | `none` |
| `qa.plan.list` | `none` |
| `qa.plan.materialize` | `qa_subject` |
| `qa.plan.rematerialize` | `qa_subject` |
| `qa.plan.retire` | `none` |
| `qa.plan_cases.replace` | `none` |
| `qa.plan_cases.sync` | `none` |
| `qa.plan_execution.abort` | `qa_subject` |
| `qa.plan_execution.adopt` | `qa_subject` |
| `qa.plan_execution.advance` | `qa_subject` |
| `qa.plan_execution.begin` | `qa_subject` |
| `qa.plan_execution.complete` | `qa_subject` |
| `qa.plan_execution.heartbeat` | `qa_subject` |
| `qa.plan_execution.pause` | `qa_subject` |
| `qa.plan_execution.reconcile` | `none` |
| `qa.plan_execution.resume` | `qa_subject` |
| `qa.plan_review.begin` | `qa_subject` |
| `qa.plan_review.submit` | `qa_subject` |
| `qa.post_deploy.declare_none` | `qa_subject` |
| `qa.post_deploy.record_no_obligation` | `qa_subject` |
| `qa.project_default.set` | `none` |
| `qa.project_default.unset` | `none` |
| `qa.project_method.register` | `none` |
| `qa.registered_command.set` | `none` |
| `qa.requirement.add` | `qa_subject` |
| `qa.requirement.add_batch` | `item` |
| `qa.requirement.get` | `none` |
| `qa.requirement.list` | `none` |
| `qa.requirement.rebind_target` | `qa_subject` |
| `qa.requirement.supersede` | `qa_subject` |
| `qa.requirement.transfer` | `qa_subject` |
| `qa.requirement.update` | `qa_subject` |
| `qa.requirement.waive` | `qa_subject` |
| `qa.run.add` | `qa_subject` |
| `qa.run.complete` | `qa_subject` |
| `qa.run.get` | `none` |
| `qa.run.list` | `none` |
| `qa.run.record_verdict` | `qa_subject` |
| `test_machine.bridge_diagnose` | `none` |
| `test_machine.case.abort` | `qa_subject` |
| `test_machine.case.begin` | `qa_subject` |
| `test_machine.case.submit` | `qa_subject` |
| `test_machine.case_execute` | `qa_subject` |
| `test_machine.desktop_access` | `none` |
| `test_machine.get` | `none` |
| `test_machine.golden_capture` | `none` |
| `test_machine.list` | `none` |
| `test_machine.mission.access` | `qa_subject` |
| `test_machine.mission.ready` | `qa_subject` |
| `test_machine.operation.abort` | `none` |
| `test_machine.operation.begin` | `none` |
| `test_machine.operation.submit` | `none` |
| `test_machine.plan_case.begin` | `qa_subject` |
| `test_machine.plan_case.submit` | `qa_subject` |
| `test_machine.reset` | `none` |
| `test_machine.screenshot` | `none` |
| `test_machine.settings_replace` | `none` |
| `test_machine.verify` | `none` |

## Transfer a direct case

`qa.requirement.transfer` moves one unexecuted direct case to an open item in
the same project. Hold both work claims, name the destination's pinned stage,
and give a rationale; both items retain the receipt. Read
`yoke qa requirement transfer --help` and [requirement discharges](../verification/requirement-discharges.md).

## Adopt captured QA after restaffing

`qa.plan_execution.adopt` transfers an ended predecessor's execution to its
item's current work-claim holder and writes a durable transfer receipt. Use
`yoke qa plan adopt --help`, then [captured QA recovery](../verification/requirement-state.md)
for the complete item/deployment recipe and continuation boundaries.

## Reconcile a stranded execution

`qa.plan_execution.reconcile` settles an execution its owner can no longer
settle: the owner ended or stopped heartbeating, or its recovery receipt is
invalid. A session needs a live steering seat covering the project; other
sessions are refused with `steering_seat_required`. A call without a session
needs the control-plane organization administrator.

```text
yoke qa plan reconcile --project P --execution-id ID --reason TEXT
```

It never settles an `active` walk (`qa_reconcile_runner_driven` names
`yoke qa plan abort`), an unfinished walk whose owner is parked
(`qa_reconcile_owner_parked`), or one still heartbeating
(`qa_reconcile_execution_live`). A held host lease needs recorded host
recovery first: the command records cancellation and refuses
`qa_reconcile_host_recovery_required`, naming the exact
`yoke test-machine reset` command, or `operator-release` when the case
declares no baseline. A mission's own review lease and released leases need
no proof. A pending review with a judgeable capture (artifacts, not
degraded) passes to the caller, and `next_command` names its `review-begin`.
Otherwise the review closes and the execution settles as aborted with no
verdict. Each run writes a `qa_plan_execution_reconciliations` receipt with
the caller, reason, prior state and owner, and released leases, atomically
with the settlement. `qa_recovery_receipt_invalid`,
`qa_abort_walk_end_required` for an ended owner, and adoption without a
provable predecessor name this command with its arguments.

## Case execution and evidence

Requirements attach to the named subject and valid workflow transition. Batch
creation validates each row against the claimed item and emits per-row results.
Read lists filter by item, epic or deployment-run subject; run rows expose
execution status. Gate summary is transition-scoped. Case execution owns one
immutable case, its source/target, lease and final evidence; no aggregate Browser
execution shortcut substitutes for that requirement.

Browser context echoes its resolved subject. Item cases use branch preview
deployment evidence; deployment cases use that run's registered target origin
and served-revision probe. The requested lineage or an older readiness receipt
never proves the revision currently served. Standalone cases keep their own
project/plan authority. [QA records](../verification/model/qa.md).

Run add/complete form the capture lifecycle. Reviewer-derived outcomes remain
`needs_review`, even with provisional verdict, until linked review settles them.
Recording may carry the start-bound execution claim: it must match the case/run
subject and its permitted window, preserving a long gate's earned result after
handoff. Missing/out-of-scope authority refuses.

Artifact add accepts one typed handle or exclusive inline bytes/filename.
Hosted evidence uses the paired portable evidence plane; unresolved/nonportable
storage refuses. Artifact read and plan review-begin use that same paired
plane as captures; local universes retain local reads. A missing pair names
`evidence_plane_unresolved` and the connection repair; a failed relay never
falls back to local storage. Rehome stores recorded bytes and CAS-updates the same artifact,
retaining run, verdict, review and old-handle/hash metadata; object-store evidence
reports unchanged. Read returns recorded local path when server cannot serve it.

Test-machine operations retain host authorization, leases, capability evidence,
substrate identity, captured proof and review. Do not replace registered method
configurations during execution. Read the operation's `--help` and applicable
QA method protocol before driving or recording a case.
