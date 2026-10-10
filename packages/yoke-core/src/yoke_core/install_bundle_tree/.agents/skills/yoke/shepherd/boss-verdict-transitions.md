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

Read ACs from stored spec, body if empty, then existing requirements. For each
testable checkbox AC (- [ ] AC-N: or plain checkbox) add missing explicit
blocking ac_verification with verification phase/ac_derived source and its
description as success policy:

```bash
yoke qa requirement list --item ITEM --json
yoke qa requirement add --item ITEM --qa-kind ac_verification --qa-phase verification --workflow-transition QA_STAGE --blocking-mode blocking --requirement-source ac_derived --success-policy "{AC description}"
```

No ACs and no existing requirement: one blocking implementation_review,
seeded_default source, "Implementation matches the item spec".
Duplicate adds create rows; do not call them idempotent. Reentry matches
existing source/AC/transition and preserves legitimate requirements.
Browser/command/machine methods come from attached plans or explicit method-backed
requirements; never infer/duplicate them here. Inspect each write/readback;
a failed seed stops with named requirement/recovery, never swallowed green.
Next: [finalize.md](finalize.md).
