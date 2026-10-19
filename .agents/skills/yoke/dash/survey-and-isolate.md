# Dash — survey the complete touch set, then isolate

## Bounded survey

Before isolation, discover only far enough to name likely targets.
Source/test roots come from project rules or tracked roots; enumerate with
`rg --files` before reading. No invented conventional roots, unmatched zsh
globs or guessed implementation paths. Prefer concrete files over directories.
Deep tracing and edits belong in the lane.

Use `direct_workflow.dash.survey`:

```text
yoke direct-workflow dash survey ITEM --path <path> --json
yoke direct-workflow dash survey ITEM --no-changes --json
```

The two forms are exclusive; no-changes needs a grounded no-edit finding,
never a placeholder. Every survey call replaces the entire stored touch set;
repeat all required paths on each call. Rediscover through
`yoke direct-workflow conflict-survey status ITEM --json`.
Receipt `touch_path_update="replace"` echoes the whole set.

Read every path_sizes count, headroom, at/over flag, limit, classification and
exists. New and existing-empty both count zero; exists distinguishes them.
Do not open/select a file that is not authored yet. At/over-limit is a
preimplementation split/home decision, not a problem deferred to commit.

## Independent policy axes

Enabled File Budget: persist complete edit targets, responsibilities and
survey sizing in the spec's File Budget through
`items.structured_field.section_upsert`.
Disabled: no invented section. Claims enabled/budget off: survey supplies
claim scope. Both enabled: pair full enumerations. Budget enabled/claims off:
retain sizing/conflict evidence without registering. Neither: spec and
survey still define scope. Never remove a required file to clear a contact.

## Contacts

Survey contacts are advisory, including when path claims are off. A shared
filename alone does not stop Dash. Read both scopes and record which sections
are independent or what requires ordering; choose from that evidence:

- Independent edits may proceed; same-file integration is resolved at merge.
- If you need holder evidence, ask an addressable holder for that evidence
  through an available harness-native task channel (`send_message_to_thread`
  only where the harness offers it). If unavailable, give the operator the
  exact holder session id and wait; do not substitute Fleet item/session mail.
- Ordered edits wait for the holding work to land, proved by merge receipt,
  merged_at or ancestry, then re-run the survey.
- A directory used only for discovery: narrow it to the complete
  concrete file set before preparation, repeating all required paths.
- A true scope or authority decision with insufficient evidence: route the
  holder, paths and decision via `yoke say --steering`. Preserve the full scope.
  Do not invent an independence attestation.
- Actual scope/authority/requirement decision: follow
  [escalate.md](escalate.md). Larger scope alone is not a boundary.

## Selected claims and independent overlap

Dash owns its survey and overlap classification; it does not route to Refine.
When path claims are enabled, register/widen every required file before
preparation. A refused registration remains a real coverage gate. For an
independent overlap, build the same evidence packet used by Refine:

```text
yoke claims path coordination-decision-build --item ITEM --conflicting-claim CLAIM_ID --paths SHARED_PATHS
yoke items dependency add ITEM HOLDER dash --gate-point coordination_only --rationale "<decision=coordination_only; shared_paths; conflicting_claim_id; independence_evidence naming each item's disjoint functions/sections; why_order_matters=absent>"
```

Read both specs and the packet; rationale cites the shared physical files,
disjoint edits, lack of coupling and packet timestamp. Then retry complete
registration and survey. Same-file merge conflicts still resolve at landing.
Ordered edits wait for the holder's proven landing before registration;
uncertain independence goes to steering with evidence. The preparation call
validates coverage; it does not author it. Read dependency-add help first: if
its source choices lack dash, the control-plane operator must serve the Dash
attestation capability; route via `yoke say --steering`, preserving scope.

## Change a mistaken path-claim selection

The work holder or a live steering seat covering the item can use the existing
registered `workflows.item_posture.amend` surface:

```text
yoke workflows item-posture amend ITEM --key path_claims --clear --reason "selected by mistake"
```

Read its help first. Clear restores the pinned workflow default; Dash's
optional policy means coverage is no longer required. Survey remains required.
Live claims must first be released by the holder; the refusal names each claim
and release recovery. If that release surface is not served, send its refusal
via `yoke say --steering` for the control-plane operator. A required pinned
policy stays required after clear. To select coverage, use --value true.

## Prepare immediately

Before deeper reads, tracing or edits:

```text
yoke direct-workflow worktree prepare ITEM --workflow dash --json
```

No environment override is required. HTTPS skips best-effort local validation
provisioning; governed rehearsal remains database-change authority.
Use returned absolute worktree_path for reads, edits, tests and git.
lane_orientation owns package/test roots and focused_test_command;
run_recipes owns lane execution. Cursor stays rooted at its conversation home;
do not remount into a lane. Use an explicit live working_directory if Shell
would inherit a deleted cwd.

Preparation reuses the claim, validates selected coverage, activates it,
verifies current tracked upstream, and creates/reuses the registered lane.
It uses the item's own project machine mapping and refuses a missing mapping
rather than borrowing this repo. Repair a wrong recorded path through
item-worktrees path-record. One project/one item/one lane; extra-project work
needs a linked companion and the scope decision in escalation.

## Activate or resume

Read `yoke workflows item get ITEM --json`, then
`yoke workflows version get WORKFLOW VERSION --json`.
WORKFLOW is result.workflow_id. VERSION is result.workflow_version,
the version number, not workflow_version_id.
LIVE_STAGE comes from status; NEXT_STAGE is the unique declared forward edge
from it, using stage order to separate rework. Confirm the live half-open Dash
binding. Missing/ambiguous edge refuses workflow_next_stage_ambiguous; ask the
workflow owner, never invent a route. Skip activation when resuming an already-active lane.

```text
yoke lifecycle transition ITEM --from LIVE_STAGE --to NEXT_STAGE --reason "Dash execution started"
```

The conflict_survey gate requires readable full scope and rereads contacts,
but overlap does not block the transition. The `work_claim_activation` gate
requires this session's claim. No-changes skips git isolation; otherwise the
registered worktree is required. Next: [implement.md](implement.md).
