# Usher — delivery

Merge-only reports landed identity and declared delivery wait, retains the
claim under its mandate and stops; a successful merge is not successful release.
Otherwise group landed items by project and projected deployment_flow.value.
Read actual flow target_tier and status; disabled definitions cannot start.
Successful empty/no flow or registered internal/merge-only convention is
Route A. A non-internal unresolved read is unresolved Route B, never guessed
deploy-free. Usher executes registered policy, not project-specific topology.
Run status/current_stage and membership own delivery proof; events do not.

## Route A: verified no delivery

```text
yoke watch merge done-transition -- PREFIX-N --skip-deploy
```

This records out-of-band delivery and is valid only for a flow genuinely
delivering nothing. A succeeded selected-flow run belongs to Route B close-out
through yoke merge item; never misrecord it with skip-deploy.

Read actual live stage and any landed receipt before recovery. Permitted
rollback uses lifecycle.transition.execute with the pin's exact source/target,
reason and standard rollback gate; never guess release -> implemented.

| Exit | Required recovery |
|---|---|
| 0 | Read actual terminal success, continue next item. |
| 1 | Merge failure: permitted rollback, halt/report code and state. |
| 2 | Cwd/arguments/validation: permitted rollback, halt with named repair. |
| 3 | Simulation/conflict gate: permitted rollback, resolve actual gap, halt. |
| 4 | User files at risk: hard-stop, preserve state, permitted rollback, manual review. |
| 7 | Flow guard: absorb into routing; unresolved/persistent/ephemeral flow needs Route B or repaired definition read. Permitted rollback, rerun correct route without skip-deploy. |
| 8 | Empty implementation branch: evidence-only recovery below; never discard files. |
| 99 | Internal self-reexecution should be launcher-owned; surfaced exit is unexpected, halt with exact evidence. |
| Other nonzero | Unexpected failure: permitted rollback only if unlanded, preserve actual landed stage, report code/recovery and halt. |

For exit8, take the pin's permitted rollback first. Read the actual registered
implementation lane and prove path exists, git status succeeds, and no modified
tracked OR untracked file remains:

```text
yoke item-worktrees get PREFIX-N --lane-role implementation --field path
git -C ABSOLUTE_REGISTERED_LANE status --porcelain --untracked-files=all
yoke item-worktrees release PREFIX-N --all-active --reason evidence-only-recovery
```

Only then release: adapter repeats fixed-reason, pinned review stage,
exactly one active implementation lane and matching cleanliness attestation. Failed
path/status/attestation stops; preserve/commit files before retry. Resume Usher.
Future no-worktree requires explicit user authorization or pinned none policy;
never prescribe an unrequested no-worktree flag.

## Route B: item-bound runs

Current mandate may reserve creation/execution to a batching orchestrator.
Honor that custody: report exact landed identity and wait, do not create a run.
Otherwise read [delivery rules](../../../../.yoke/docs/reference/agent-rules/delivery.md)
and hold DEPLOY for the project before first composition/execution:

```text
yoke claims coordination-claim acquire --project PROJECT --key DEPLOY:PROJECT --reason "usher deploy batch"
```

Refusal names holder: wait/coordinate, no workaround. Stranded holds require
human signed-in exact reviewed holder release, outside harness:

```text
yoke coordination-claim release --project PROJECT --key DEPLOY:PROJECT --claim-id {claim_id} --holder-session-id SESSION --reason REASON
```

The action verifies unchanged holder/claim and writes durable reason/WARN;
agent sessions cannot perform that recovery.

Before new composition, find the existing member run:

```text
yoke deployment-runs find-by-item PREFIX-N --status executing --json
yoke --env CONTROL_PLANE deployment-runs start-for-item PREFIX-N --project PROJECT --flow FLOW --environment ENVIRONMENT --json
```

An executing run resumes from its authoritative stage instead of duplicate
creation. Start resolves target, creates, enrolls candidate-carried unheld
delivery-ready work (including cancelled-run residue) and validates composition.
Ordinary external delivery uses selected HTTPS transport; serving-API selfdeploy
refusal goes to its operator with named recovery. Do not switch authority silently.

Remaining eligible items auto-enroll. Explicit add is only for an intended member
whose code is not in candidate; it needs same DEPLOY hold, created run, matching
project/bound source and compatible workflow:

```text
yoke deployment-runs add-item RUN-ID PREFIX-N
yoke deployment-runs validate-composition RUN-ID
```

Unresolved target/multiple environments requires explicit operator selection,
then retry with environment. Composition failure halts, no partial execution.
Item-scoped QA needs delivery custody; carried/owed members without it refuse
item_qa_flow_without_delivery_custody. A completion flow with unheld eligible
work but no members refuses item_qa_run_without_members at composition and
later dispatch/gates. A legitimately target-out memberless run owing no delivery
records item_qa_no_member_owes_target, not a fabricated member pass.

Preview side choices remain explicit: inspect actual project preview occupancy
before start; occupied chooses overwrite/new name/abort. New lineage must have
an authoritative created identity passed as release-lineage; after start attach
the preview through its authoritative owner. Read available retained operations
and project Pack policy. The current deployment registry/catalog exposes no
lineage-create or preview-claim mutation: if required, stop as
preview_lineage_mutation_unavailable and escalate exact operation plus checked
surfaces to control-plane operator. No invented adapter, raw SQL or claimed
occupancy/lineage success. Reuse already verified identities only.

Pipeline automatically seeds run QA; do not seed manually. Verify merged commit
ancestry against the flow/environment-resolved branch, never hardcode main.
Execute via the manifest long-command/watcher surface and continue its handle
to exit; pipeline polls external systems itself. Do not poll/relaunch.

```text
yoke --env CONTROL_PLANE watch deploy -- RUN-ID
```

Only proven premerge ephemeral work and resolved successor stage permit
watch deploy -- RUN-ID --from-stage NEXT_STAGE. Serving-API refusal escalates to operator.

| Exit | Required action |
|---|---|
| 0 | Close each member via selected-flow evidence and verify actual item stage. |
| 1 | Stage failure: release every member claim with usher-halt-deploy-stage-failure, then DEPLOY hold, then halt/resume summary. |
| 2 | Exact run awaits human approval; stop with registered approval command, retain DEPLOY across wait. Each later approval is a new exact-run decision. Resume deploy-only at authoritative stage after approved receipt. |
| 3 | Setup/preview/lineage/infrastructure failure: member claim releases usher-halt-deploy-infra-failure, then DEPLOY release, then halt. |
| Other | Preserve run/current stage, diagnose named failure and report; no success shortcut. |

```text
yoke merge item PREFIX-N --result "what shipped" --verification "RUN-ID, stages and QA"
yoke qa plan run --deployment-run-id RUN-ID --stage STAGE --member PREFIX-N
yoke deployment-runs approve RUN-ID --note "operator decision" --json
yoke claims work release --item PREFIX-N --reason usher-halt-deploy-stage-failure --json
```

Own-flow close-out never uses done-transition skip-deploy. Unsatisfied member QA
must name BOTH run stage and member; an unscoped run-wide pass cannot credit it.
Approval is operator action, not agent self-approval. For infra failure use its
different release intent. Any failed member release must name failure/holder;
don't claim clean recovery while it stays held. Never use completed for a halt.

After final group settles (or halt1/3 after member releases), release each
project hold before summary; approval2 retains it:

```text
yoke claims coordination-claim release --project PROJECT --key DEPLOY:PROJECT --reason "usher deploy batch complete"
```

Continue to [finalize](finalize.md). Level-change handoff takes precedence over
release wait; follow current mandate and registered successor contract.
