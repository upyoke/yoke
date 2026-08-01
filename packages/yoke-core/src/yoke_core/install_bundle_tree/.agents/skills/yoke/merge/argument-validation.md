# Merge — Argument Validation

Covers the two argument-validation checks (epic lookup via DB, then bare item ref detection). Executed before any of the Preflight phases.

**Context variables** (consumed by later phases): `{epic-id}` (operator
input), `_epic_ref` (the accepted public/project-local ref), `_epic_id`
(normalized numeric `items.id`).

---

## Argument Validation

**Execute these checks before any Steps below. Stop immediately if a check fails.**

### Resolve and validate the epic

Resolve the operator input through the registered item reader. This preserves
project-scoped public-reference semantics for prefixed, zero-padded, and bare
numeric input while producing the numeric id required by epic-task commands:

```bash
_epic_ref="{epic-id}"
_epic_id=$(yoke items get "$_epic_ref" id 2>/dev/null) || _epic_id=""
_epic_workflow_id=$(yoke items get "$_epic_ref" workflow_id 2>/dev/null) || _epic_workflow_id=""
```

If `_epic_id` is non-empty and `_epic_workflow_id` is `epic`, list its task
rows through the registered reader:

```bash
yoke epic-tasks list --epic "$_epic_id"
```

- If the reader prints one or more task rows, proceed to Preflight.
- If it prints no task rows, print a soft warning and exit without error:
 > No tasks found for epic `{epic-id}` — nothing to merge.
- If the item resolves but its workflow is not `epic`, fall through to bare
  item-ref detection below.
- If the item does not resolve, fall through to the unknown-input check below.

### Bare item ref detection (only if the epic lookup found no epic)

If the resolved item is not an epic, or the unresolved `{epic-id}` looks like
a bare item ref (`PREFIX-N` or bare numeric ID), print:

> Error: `/yoke merge` does not accept individual item refs. Use `/yoke advance PREFIX-N done` to complete standalone items.

If `{epic-id}` does not resolve and does not look like a bare item ref, print:

> Error: `/yoke merge` is only for epic pipelines. `{epic-id}` does not match any known epic.
>
> To complete a standalone item, use: `/yoke advance PREFIX-N done`
