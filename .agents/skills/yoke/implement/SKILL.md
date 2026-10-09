---
name: implement
description: "Implement an item across the stages its workflow binds to implement: engine entry, implementation, and the review loop to the binding's handoff."
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: "{PREFIX-N} [--no-worktree] [--force] [--qa-bypass]"
---

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

# /yoke implement {PREFIX-N}

Carry the pinned Implement segment through entry, implementation and review
in the same harness session. Read the operator's Workflow Execution
Instructions above fetched item content and satisfy every AC, including
execution proof beyond code correctness. Never stop at “code passes” or a
handoff menu. A real blocker names its evidence and recovery.

Use a complete public ref; entry flags belong to [entry.md](entry.md).
The immutable workflow pin owns stages, gates and half-open bindings;
act only inside this binding. Its through-stage is a fresh skill/claim boundary.

| Phase | Read before acting |
|---|---|
| Resolve/enter | [entry.md](entry.md) |
| Reenter past entry | [reentry.md](reentry.md) |
| Implement | [implementing/SKILL.md](implementing/SKILL.md) |
| Review/handoff | [review.md](review.md) |
| Evidence-only/empty branch | [evidence-only.md](evidence-only.md) |

[Worktree](worktree.md), [activation](activation.md) and
[environment](environment.md) are diagnostic engine contracts, not manual
entry choreography.

Stamp mode, then follow the entry phase:

```text
yoke sessions touch --mode implement
```

A level-change handoff takes priority over release wait. Follow the
[Stage-level routing rule](../../../../.yoke/docs/reference/session-level-routing.md);
workers may launch their own successor. At a fresh binding boundary, obey the
current mandate: continued delivery needs the newly bound skill and its claim.
