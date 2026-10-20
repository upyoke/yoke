---
name: polish
description: "Review code and tests in existing worktree lane(s) against item artifacts, make finishing fixes, run verification, and commit."
argument-hint: "{PREFIX-N}"
---

# /yoke polish {PREFIX-N}

Review, fix, verify and commit the item's lanes, then advance through its
pinned polish binding. Never push or open a PR by hand.

Phase map: steps: [parse-and-claim](parse-and-claim.md), [context](context.md),
[doctrine](doctrine.md), [simplify-pass](simplify-pass.md), [review](review.md),
[fixes](fixes.md), [verify-and-commit](verify-and-commit.md), [advance](advance.md).
