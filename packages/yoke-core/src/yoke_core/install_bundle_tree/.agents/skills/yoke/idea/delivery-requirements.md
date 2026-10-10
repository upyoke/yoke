# Idea / Dash — Delivery Evidence Intake

Run after create and work claim only for requested running screenshots/visual
proof, named environment/preview QA or human approval. Ordinary implementation
and branch review previews stay their existing workflow QA; no second store,
case catalog, flow engine or hidden stages.

## Placement and suitable item flow

Follow [Where a Browser case runs](../../../../.yoke/docs/reference/browser-scenarios.md#where-a-browser-case-runs):
visibility determines verification/post_deploy phase, target and declared
transition; no served surface selects approval_on_done. A screenshot specializes
a case, not a new flow if existing sequence/verdict already fits.

Resolve explicit item flow, workflow-specific delivery_default, then project
default. Task stays exempt per actual laneless policy; omit flow, never none.
```bash
yoke deployment-flows get <flow-id> --json
yoke deployment-flows validate --project <project> --stages-file <local-stages-path> --target-tier persistent --environment <environment> --status active --json
```

Disabled cannot attach. execution_supported=false means keep definition
disabled and report serving-schema floor; do not weaken requested evidence.
An unsuitable default gets a suitable **item-only** active flow:
```bash
yoke items scalar update PREFIX-N --field deployment_flow --value <flow-id>
```
Never rewrite shared defaults for one item.

## Persist an explicit method-backed case

Use registered `qa.requirement.add`; its CLI below authors the existing QA row.

Dash's optional attachment needs the selected verification method:
```bash
yoke workflows item-posture amend PREFIX-N --verification-method browser-inspection --reason "intake screenshot request"
```
At filing, the Dash shortcut passes that method. For unserved changes,
approval_on_done replaces Browser proof; at-file approval flag or registered
posture amendment applies only where the pinned definition allows.
Issue/Epic/Blitz use their existing QA gates, not invented Dash posture.

Bind --workflow-transition to the actual stage owning the declared phase.
Verification belongs to the selected-method review/qa_verification stage;
post_deploy/manual_acceptance belongs to pinned release wait/done or deployment
run. Never bind post-merge acceptance to review. Phase is declared, not inferred
from URL/environment/prose; verification may target an existing production
server before merge. Review gates **do not wait for an environment** created
after merge.

Frozen admission copies correctly bound post_deploy source onto its candidate
deployment subject. Completion accepts the admitted copy on its chosen member
run via the acceptance ladder; it does not re-run or waive the original.
A prior candidate's pass does not satisfy a later run, including a passing run
recorded on the original intake row itself. A run that never admitted this
source or no run at all is insufficient. Failed/cancelled member attempts do
not erase a prior succeeded completion run's accepted copy. A later release
containing the merge without enrolling the member proves delivery but adds no
source-QA copy and does not replace the member run. Manual acceptance retains
its phase gate.

Example for a pin whose post-deploy transition is release:
```bash
yoke qa requirement add --item PREFIX-N \
  --method-id browser-inspection --qa-phase post_deploy \
  --target-env ENV --requirement-source explicit \
  --instructions "Capture the requested running surface on ENV." \
  --expected-outcome "The screenshot shows the requested behavior on ENV." \
  --method-config '{"steps":[{"action":"navigate","route":"/ROUTE"},{"action":"screenshot","capture":true,"label":"intake"}]}' \
  --workflow-transition release
```

Use its actual bound transition, not the example when it differs.
Nonvisual evidence uses command method with matching phase/target.
Premerge visual proof uses verification placement. Read back:
```bash
yoke qa requirement list --item PREFIX-N --json
```
Require phase, environment and complete instructions/expected outcome/config.
Intake persists; it neither executes QA nor creates deployment runs.

## Explicit approval policy

Evidence alone **does not** add approval. A screenshot does **not** add approval,
approval_on_done or a human reviewer.

"Have me approve it" requires verdict.mode=required_human on the **item-scoped QA stage**
whose configured target is what the operator requested. Read the flow;
do not assume a kind: persistent_environment names ENV; run_preview names the
candidate without environment. Reviewers require this operator in actors with
mode=all, not an ANY role, run-scoped QA or non-QA execution stage.
Missing reviewer policy is invalid.

`human_if_unsure` can pass without asking; only use it for explicitly conditional
approval. Keep a compatible reviewer requirement already requiring this operator.
Do not replace a matching policy or weaken required_human.

Referenced/immutable/shared-default candidate needs a validated new item-only
definition then item flow assignment. Never `update-stages` a shared,
referenced or immutable definition. No fallback reviewer system.
