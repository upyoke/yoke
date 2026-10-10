---
name: polish
description: "Review code and tests in existing worktree lane(s) against item artifacts, make finishing fixes, run verification, and commit."
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: "{PREFIX-N}"
---

# /yoke polish {PREFIX-N}

Review and finish an item's existing implementation lanes against its spec,
ACs and plan; verify, commit, and advance through its pinned polish segment.
Both standalone invocation and workflow routing authorize this operation.
Require a complete public ref; bare numbers are refused.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

Read the item pin and exact immutable version. The half-open skill binding
containing the live stage must belong to polish. Its entry and through-stage
bound this command; refresh the pin after each transition and before handoff.
Failed verification leaves the item at its working stage.

Require existing registered lanes: one implementation lane or every task lane
of a multi-lane item. Preserve unrelated uncommitted work. Commit specific files
locally; never push or create a PR by hand. The registered CI gate owns publication.

## Phase map

Read and execute these phases in order, one at a time.

| Phase | Read before acting |
|---|---|
| 1–3. Resolve, claim, validate lanes, activate | [parse-and-claim.md](parse-and-claim.md) |
| 4–5. Artifacts and surrounding survey | [context.md](context.md) |
| First diff pass: simplify | [doctrine.md](doctrine.md), then [simplify-pass.md](simplify-pass.md) |
| 6. Review against all ACs | [review.md](review.md) |
| 7. Apply finishing fixes | [fixes.md](fixes.md) |
| 8–9. Verify and commit | [verify-and-commit.md](verify-and-commit.md) |
| 10–15. QA, bound transition, release, report | [advance.md](advance.md) |

Simplify is a **single sequential pass**, before staleness review or test reruns;
do not delegate three parallel axis passes. A clean diff continues normally.
Each lane must close its gaps before the parent can advance.

## Continuity and start

Checkpoint current execution state with `items.progress_log.append` in the
**Progress Log**; spec and technical plan express intent, and graph planning
fields are not execution logs. Start with parse-and-claim.

A `handoff` with `reason=level_change` takes precedence over a release wait.
Follow `.yoke/docs/reference/session-level-routing.md`; workers may launch
their own successor.
