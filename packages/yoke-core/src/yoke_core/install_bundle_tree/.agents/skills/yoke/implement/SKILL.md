---
name: implement
description: "Implement an item across the stages its workflow binds to implement: engine entry, implementation, and the review loop to the binding's handoff."
argument-hint: "{PREFIX-N} [--no-worktree] [--force] [--qa-bypass]"
---

# /yoke implement {PREFIX-N}

Carry the pinned Implement binding through entry, implementation and review
in this session. Prove every AC; never stop at "code passes" or a menu.

```text
yoke sessions touch --mode implement
```

Read [entry.md](entry.md), then [implementing/SKILL.md](implementing/SKILL.md),
then [review.md](review.md). A level-change handoff beats a release wait:
[levels](../../../../.yoke/docs/agents/levels.md).
