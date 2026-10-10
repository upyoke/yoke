# QA Function Catalog

Read [envelope and authority](functions.md) first. `none` means no dispatcher work-claim check; handler permissions still apply. Read command help for the live payload and serving floor.

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
| `qa.plan_cases.replace` | `none` |
| `qa.plan_execution.abort` | `qa_subject` |
| `qa.plan_execution.advance` | `qa_subject` |
| `qa.plan_execution.begin` | `qa_subject` |
| `qa.plan_execution.complete` | `qa_subject` |
| `qa.plan_execution.heartbeat` | `qa_subject` |
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
project/plan authority. [QA and sessions](qa-and-sessions.md).

Run add/complete form the capture lifecycle. Reviewer-derived outcomes remain
`needs_review`, even with provisional verdict, until linked review settles them.
Recording may carry the start-bound execution claim: it must match the case/run
subject and its permitted window, preserving a long gate's earned result after
handoff. Missing/out-of-scope authority refuses.

Artifact add accepts one typed handle or exclusive inline bytes/filename.
Hosted evidence uses the paired portable evidence plane; unresolved/nonportable
storage refuses. Rehome stores recorded bytes and CAS-updates the same artifact,
retaining run, verdict, review and old-handle/hash metadata; object-store evidence
reports unchanged. Read returns recorded local path when server cannot serve it.

Test-machine operations retain host authorization, leases, capability evidence,
substrate identity, captured proof and review. Do not replace registered method
configurations during execution. Read the operation's `--help` and applicable
QA method protocol before driving or recording a case.
