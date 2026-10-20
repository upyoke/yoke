---
name: implement
description: "Implement an item across the stages its workflow binds to implement: engine entry, implementation, and the review loop to the binding's handoff."
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: "{PREFIX-N} [--no-worktree] [--force] [--qa-bypass]"
---

<!-- BEGIN GENERATED: field-note-directive -->
File a field note each time a recipe, help text or refusal is wrong or missing, or you spot a bug outside your task — before moving on. If you already filed the same problem, add `--correlation-id <that note's id>`:
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
<!-- END GENERATED: field-note-directive -->

# /yoke implement {PREFIX-N}

Carry the pinned Implement binding through entry, implementation and review
in this session. Prove every AC; never stop at "code passes" or a menu.

```text
yoke sessions touch --mode implement
```

Read [entry.md](entry.md), then [implementing/SKILL.md](implementing/SKILL.md),
then [review.md](review.md). A level-change handoff beats a release wait:
[levels](../../../../.yoke/docs/agents/levels.md).
