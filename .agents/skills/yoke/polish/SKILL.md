---
name: polish
description: "Review code and tests in existing worktree lane(s) against item artifacts, make finishing fixes, run verification, and commit."
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: "{PREFIX-N}"
---

# /yoke polish {PREFIX-N}

Review, fix, verify and commit the item's lanes, then advance through its
pinned polish binding. Never push or open a PR by hand.

<!-- BEGIN GENERATED: field-note-directive -->
File a field note each time a recipe, help text or refusal is wrong or missing, or you spot a bug outside your task — before moving on. If you already filed the same problem, add `--correlation-id <that note's id>`:
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
<!-- END GENERATED: field-note-directive -->

Steps: [parse-and-claim](parse-and-claim.md), [context](context.md),
[doctrine](doctrine.md), [simplify-pass](simplify-pass.md), [review](review.md),
[fixes](fixes.md), [verify-and-commit](verify-and-commit.md), [advance](advance.md).
