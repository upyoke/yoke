---
name: polish
description: "Review code and tests in existing worktree lane(s) against item artifacts, make finishing fixes, run verification, and commit."
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: "{PREFIX-N}"
---

# /yoke polish {PREFIX-N}

Standalone capability for polishing an in-progress implementation. Locates the existing implementation worktree lane set for a backlog item, reviews code and tests against the item's artifacts (spec, ACs, technical plan), makes finishing fixes, runs verification, and commits when changes are needed. Issue items usually have one item worktree; epic items may have multiple task worktrees from the worktree plan.

This is an explicit, operator-invoked capability that Codex can execute directly.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Arguments

- `{PREFIX-N}` — Backlog item ID. Requires a complete `PREFIX-N` public ref; bare numbers are refused.

## Workflow segment

Read `yoke workflows item get ITEM --json`, then its exact pin with
`yoke workflows version get WORKFLOW VERSION --json`. Polish owns the
half-open `definition.skill_bindings` interval containing the live stage
only when that binding's `skill_id` is `polish`. Its `from_stage_id` is
the entry and its `through_stage_id` is the handoff boundary.

Activate and complete through the definition's forward transitions using
`yoke lifecycle transition`. A resumed working stage stays in place during
review. Successful polish stops at the bound handoff stage and renders
`next_skill_id` from a fresh item read. Failed verification leaves the item
at its current working stage; it cannot cross the handoff boundary.

## Constraints

- Requires existing implementation worktree lanes. If no lane exists, stop with guidance.
- Code edits and test fixes are expected when needed.
- Commits follow standard Yoke commit discipline (specific files, descriptive messages).
- Both standalone and routed modes advance status on successful completion.
- Respect existing uncommitted work in the item's worktree. Do not discard or reset unrelated edits.
- **Never push branches or create pull requests by hand.** Commit locally;
  the registered CI verification gate owns any required publication.

## Phase map — read one file, at the phase it governs

Polish executes its passes in order. Each lives in its own file; read and
execute them in sequence, one at a time.

| Phase | What it does | Read before acting |
|---|---|---|
| 1–3. Parse and claim | Parses the argument, locates the existing worktree lane set, activates polish through the claim + status-transition hard gate. Stops if the item is missing, the lane set does not exist, or another session holds the claim. | [`parse-and-claim.md`](parse-and-claim.md) |
| 4–5. Gather context | Reads spec, body, technical plan, and test results, then surveys recent main commits, active pipeline items, and recently-done items for drift, overlap, and supersession. | [`context.md`](context.md) |
| Simplify pass | The first pass over the worktree diff — reuse, quality, efficiency, future-concept. Runs before staleness review and before any test re-run. | [`doctrine.md`](doctrine.md), then [`simplify-pass.md`](simplify-pass.md) |
| 6. Review | Examines the worktree diff against `main`, runs the verification checklist, walks the review dimensions, emits a structured report. | [`review.md`](review.md) |
| 7. Apply finishing fixes | AC closure, test co-modification, dead-code deletion, blast-radius cleanup, documentation freshness, and the DB-claim stop-and-amend gate. | [`fixes.md`](fixes.md) |
| 8–9. Verify and commit | Runs the project's registered test commands, then commits with a scoped `git add`. No push, no pull request. | [`verify-and-commit.md`](verify-and-commit.md) |
| 10–15. Complete the bound segment | Re-runs attached QA against the polish commit, captures the summary, transitions to the binding's handoff stage, releases the claim. | [`advance.md`](advance.md) |

Polish runs the three simplify axes as a **single sequential pass**, not a
parallel three-sub-agent fan-out. v0 keeps the pass sequential by design.

## Multi-turn polish session continuity
Polish frequently spans multiple turns when the diff is large or the simplify pass surfaces re-work. For checkpoint notes that successor agents need to resume after compaction, write to the **Progress Log** section on the item — see `AGENTS.md > Progress Log — long-running execution context on items`. Do NOT use `shepherd_log` (epic-only) or the spec/technical_plan fields (intent, not state).

## Start

Read [`parse-and-claim.md`](parse-and-claim.md) and execute it.

A `handoff` with `reason=level_change` takes precedence over a release wait.
Follow the harness-neutral Stage-level handoff rule in
`.yoke/docs/reference/session-level-routing.md`; workers may launch their own successor.
