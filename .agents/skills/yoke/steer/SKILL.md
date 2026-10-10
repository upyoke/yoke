---
name: steer
description: "Direct-mode entrypoint — itemless steering loop over a strategy doc, defaulting to CURRENT-PLAN."
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: "[STRATEGY-DOC-SLUG] [--project P ...]"
---

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

# /yoke steer [STRATEGY-DOC-SLUG] [--project P ...]

Itemless autonomous steering of a claimed strategy document, defaulting to
CURRENT-PLAN. Read its intent, reconcile live frontier/reports, staff executors,
and write current plan state. The coordinator never implements.

## Phase map

| Phase | Read before acting |
|---|---|
| Parse/read/take paired seat | [scope-and-authority.md](scope-and-authority.md) |
| Continuous pass | [loop.md](loop.md) |
| Safe stop/handoff/release | [close-out.md](close-out.md) |
| Staff, judge or restaff | [worker-lifecycle.md](worker-lifecycle.md), [model-selection.md](model-selection.md) |
| Launch/settle worker | [worker-launch.md](worker-launch.md) |
| Attach fleet stream | [watching.md](watching.md) |
| Triage findings | [fleet-findings.md](fleet-findings.md) |
| Blitz document handoff | [blitz-handoff.md](blitz-handoff.md) |
| Batch merged delivery | [release-batches.md](release-batches.md) |
| Exact function lookup | [function-reference.md](function-reference.md) |

Standing invariants:

- One atomic steering acquire pairs a steering-scope claim and document lock;
  the document and linked items are durable state. Scope/links/overlap and role
  mail are governed by scope-and-authority. No doc-less continuation.
- Use steering-scope claim, steering claim holder, steering scope. Coordinator
  is role prose, never a durable identifier. Avoid the bare phrase "steer claim".
- Do not invoke `/yoke feed`. Feed and steer are unrelated. No new scheduler:
  existing message wakes, fleet watcher and frontier reads drive the loop.
- Each item keeps its pinned workflow and routed next_step. Never convert or
  re-file it to fit a remembered workflow. Verify pin/full command before
  claiming a capability absent or filing replacement work.
- New filing defaults to Dash; genuinely laneless/merge-free Task, required
  Issue/Epic/Blitz structure, or operator direction are exceptions. Name
  --strategy-doc SLUG at intake. Workers merge; the steerer batches delivery
  at one verified source. Mandates prohibit worker deployment-run creation.
- All launches use registered preview/create, including raw itemless mandates.
  Effective item level and judged leg choose staffing; item-bound --level records
  an every-stage override. No alternate native/app launch after Yoke refusal.
- Every operator-visible reply states all verified outstanding operator actions,
  blocked item and unblock condition until resolved/muted. Correct system-caused
  attribution; fold reminders into normal reply/live snapshot, no extra nag turn.
- Invoking this skill authorizes reads, claims, acknowledgements, staffing and
  document writes. Ask only at its explicit missing-document creation or
  reserved operator-decision gate.

Start with scope-and-authority; follow one current phase at a time.
