---
name: amend
description: Add, split, reassign, or remove tasks after sync. Re-verifies overlap and updates GitHub.
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: "{epic-ref}"
---


# /yoke amend {epic-ref}

Internal sub-skill called by Conduct; not operator-facing. Add, split,
reassign or remove tasks after sync. Use a complete public ref with a task graph.

<!-- BEGIN GENERATED: field-note-directive -->
File a field note each time a recipe, help text or refusal is wrong or missing, or you spot a bug outside your task — before moving on. If you already filed the same problem, add `--correlation-id <that note's id>`:
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
<!-- END GENERATED: field-note-directive -->

Hold the epic's work claim before any task, spec, plan, dependency, File Budget,
path-claim or GitHub mutation. Another holder's session id is identity, not
write authority. Stop while a dispatch for the same epic is in progress.
Every change re-verifies overlap and preserves crisp task boundaries,
current-state checkpoint and next action.

Frame amendments as system corrections (missing boundaries, stale overlap or
new execution evidence), never as “agent error” or role blame.

## Phase map — read before acting

| Phase | Read |
|---|---|
| Amend tasks and reconcile execution | [steps.md](steps.md) |
| Exact typed surfaces | [surfaces.md](surfaces.md), before a mutation |

Start with steps.md.
