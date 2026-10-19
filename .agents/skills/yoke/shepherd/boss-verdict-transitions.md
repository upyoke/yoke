# Shepherd — verdict routing and first-edge QA

READY passes; CAVEATS passes only after **every** caveat disposition and visible
artifact write. Update log, carry caveats into next prompt. NOT_READY increments
attempt and auto-retries with feedback while below MAX_ATTEMPTS; limit persists
BLOCKED, names gate/recovery and stops. No automatic force-pass.

Refresh stage: already at early planning target still requires accepted review.
Otherwise lifecycle.transition.execute targets this declared edge with exact
source/target, then readback verifies it. Refusal stops; never jump another binding.
Final successful review cascades only tasks still planning to plan-drafted through
workflow_item.epic_task.update_status; these are task-owner states, not parent
stage literals. Any task failure stops with its identity/recovery.

## Successful first edge only: selected flow

After READY/CAVEATS and status write, read spec silently, body only if empty.
Still empty: retry once after 1s, discard afterward.
Within ## Definition of Done select first anchored field-style Flow:
optional bullet/bold markers, strip markdown/space. Prose "flow:" is no selection.
Validate actual flow through registered deployment_flows.get for the project,
then items.scalar.update deployment_flow and readback.

Absent DoD/Flow/unrecognized flow: explicit advisory skip/manual selection later,
not invented success. Failed read/write is named; unreadability is not absence.

## Successful first edge only: requirements

Derive _qa_verification_stage from first post-binding stage with reviewing board
bucket and qa_verification gate. Absent: shepherd_qa_anchor_unavailable,
publish corrected definition; no literal stage substitute.

Read ACs from the stored spec, then existing plan cases and requirements.
Map every testable checkbox AC to a proving executable plan case. Attach and
materialize those cases at the derived QA stage; preserve their concrete
instructions, expected outcome and method. Missing mapping stops as
`requirement_proof_required`: author the proving case before proceeding.
Do not create a blocking `ac_verification` row from acceptance prose alone.

```bash
yoke qa requirement list --item ITEM --json
yoke qa item-plan attach --item ITEM --project PROJECT --plan-id PLAN_ID --transition QA_STAGE --qa-phase verification
yoke qa plan materialize --item ITEM --transition QA_STAGE
```

No ACs and no existing requirement: one blocking implementation_review,
seeded_default source, success policy all-pass, retains its real review writer.
Reentry matches existing plan/case/transition and preserves requirements.
Never infer a command, browser or machine method from AC prose. Inspect each
write and readback; failed coverage stops with its criterion and recovery.
Next: [finalize.md](finalize.md).
