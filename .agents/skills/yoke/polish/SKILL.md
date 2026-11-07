---
name: polish
description: "Review code and tests in existing worktree lane(s) against item artifacts, make finishing fixes, run verification, and commit."
argument-hint: "{PREFIX-N}"
---

# /yoke polish {PREFIX-N}

Review, fix, verify and commit the item's lanes, then advance through its
pinned polish binding. Never open a PR by hand.

Phase map: [parse-and-claim](parse-and-claim.md), [review](review.md),
[verify-and-commit](verify-and-commit.md), [advance](advance.md).
