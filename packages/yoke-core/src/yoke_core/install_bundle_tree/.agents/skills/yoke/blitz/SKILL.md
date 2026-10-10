---
name: blitz
description: "Execute a substantial document-led Blitz as integrated slices with continuous plan evidence."
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: "{PREFIX-N}"
---

# /yoke blitz {PREFIX-N}

Execute one refined Blitz from its single linked strategy document: the live
plan, progress log, handoff, completion and parent-reconciliation record.
The item owns identity, claims, lifecycle, worktrees, QA and delivery.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Phase map

| Phase | Read when reached |
|---|---|
| Read, bounded survey, isolate | [read-and-survey.md](read-and-survey.md) |
| Map and integrate slices | [integrate.md](integrate.md) |
| Whole review and close | [review-and-complete.md](review-and-complete.md) |
| Exact operation lookup | [function-reference.md](function-reference.md) |

## Invariants

- Complete public ref, resolving to Blitz at `refined-idea`, `implementing`,
  `reviewing-implementation`, or `release`.
- Refine must already link exactly one execution document. Keep it authoritative;
  create no child items or copy into the item body.
- The item work claim owns execution; its item-owned document claim owns revision.
  Other sessions use only append-only `Slice Log` and `Live Status`.
- Default File Budget/path claims are off; read their independent effective
  policies. Always obey the 350-line limit, survey before activation and every
  slice merge, judge each contact proceed/yield, and write only in registered
  isolated lanes. Prepare immediately after minimal path discovery, before
  deeper reading or edits.
- Main session owns slice boundaries/order, full verification, document
  completion and parent reconciliation. Migration, capability, security,
  approval and run-record invariants hold on every action.

Start: `yoke sessions touch --mode blitz`, then follow the first phase.
A `handoff` with `reason=level_change` takes precedence over release wait:
follow `.yoke/docs/reference/session-level-routing.md`; workers may launch successors.
