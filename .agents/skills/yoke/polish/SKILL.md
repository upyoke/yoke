---
name: polish
description: "Review code and tests in existing worktree lane(s) against item artifacts, make finishing fixes, run verification, and commit."
argument-hint: "{PREFIX-N}"
---

# /yoke polish {PREFIX-N}

Standalone capability for polishing an in-progress implementation. Locates the existing implementation worktree lane set for a backlog item, reviews code and tests against the item's artifacts (spec, ACs, technical plan), makes finishing fixes, runs verification, and commits when changes are needed. Issue items usually have one item worktree; epic items may have multiple task worktrees from the worktree plan.

This is an explicit, operator-invoked capability that Codex can execute directly. It does not require `/yoke do`, lane-aware routing, or lifecycle-family ownership wiring.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Arguments

- `{PREFIX-N}` — Backlog item ID. Accepts `PREFIX-N`, zero-padded IDs, or a bare number.

## Modes

Polish always advances status on successful completion, whether invoked directly (e.g., `/yoke polish PREFIX-N`) or via scheduler routing.

### Lifecycle transitions
- `reviewed-implementation` -> `polishing-implementation` (set immediately when polish starts)
- `polishing-implementation` -> `implemented` (set on successful completion)

If polish fails, cannot resolve the worktree, or leaves verification failing, the item must NOT auto-advance to `implemented`. Once polish starts, the item stays at `polishing-implementation`.

## Constraints

- Requires existing implementation worktree lanes. If no lane exists, stop with guidance.
- Code edits and test fixes are expected when needed.
- Commits follow standard Yoke commit discipline (specific files, descriptive messages).
- Both standalone and routed modes advance status on successful completion.
- Respect existing uncommitted work in the item's worktree. Do not discard or reset unrelated edits.
- **Never push branches or create pull requests.** Polish commits locally only. Pushing and PR creation belong to usher.

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
| 10–15. Advance to implemented | Re-runs browser QA and project E2E against the polish commit, captures the summary, advances to `implemented`, releases the claim. | [`advance.md`](advance.md) |

Polish runs the three simplify axes as a **single sequential pass**, not a
parallel three-sub-agent fan-out. v0 keeps the pass sequential by design.

## Multi-turn polish session continuity
Polish frequently spans multiple turns when the diff is large or the simplify pass surfaces re-work. For checkpoint notes that successor agents need to resume after compaction, write to the **Progress Log** section on the item — see `AGENTS.md > Progress Log — long-running execution context on items`. Do NOT use `shepherd_log` (epic-only) or the spec/technical_plan fields (intent, not state).

## Start

Read [`parse-and-claim.md`](parse-and-claim.md) and execute it.
