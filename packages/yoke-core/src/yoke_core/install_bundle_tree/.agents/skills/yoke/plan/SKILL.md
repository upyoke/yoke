---
name: plan
description: Invoke the Architect subagent to produce the plan shape selected by the item's pinned workflow policies.
argument-hint: "{item-id}"
---

# Internal sub-skill — called by the skill that owns plan authoring.

# /yoke plan {item-id}

Translate an item spec into a technical implementation plan. The item's
immutable workflow pin selects whether planning writes one item-level
`technical_plan` or a persisted generated-task decomposition.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Arguments

- `{item-id}` — A `PREFIX-N` reference, internal numeric item id, or lowercase
  title slug with spaces replaced by `-`.

## Authority

Never choose plan mode from `workflow_id`. Resolve the exact item pin with
`workflows.item.get`, read its logical version with `workflows.version.get`,
and interpret:

- ordered `stages` plus half-open `skill_bindings` for the current owner;
- `policies.generated_children` for decomposition storage;
- `policies.worktrees` for lane planning;
- stage gate ids for simulation requirements.

Skill names remain valid guards because this sub-skill is an implementation
detail of those registered skills. Workflow names are registry keys, not
behavior branches.

## Phase map — read one file, at the phase it governs

| Phase | You are here when | Read before acting |
|---|---|---|
| 1–4. Resolve, validate, reconcile, survey | The owning skill just invoked this sub-skill | [`resolve-and-validate.md`](resolve-and-validate.md) |
| 5–8. Architect, persist, hand back | The survey is complete | [`architect-and-persist.md`](architect-and-persist.md) |
| — Check the plan before handing back | You are about to hand the plan to the owning skill | [`review-checklist.md`](review-checklist.md) |

## Start

Read [`resolve-and-validate.md`](resolve-and-validate.md) and follow it.
