# Merge — Argument Validation

Covers the two argument-validation checks (epic lookup via DB, then bare item ref detection). Executed before any of the Preflight phases.

**Context variables** (consumed by later phases): `{epic-id}` (numeric, `YOK-` stripped).

---

## Argument Validation

**Execute these checks before any Steps below. Stop immediately if a check fails.**

### Epic validation via DB (check DB first)

Strip any `YOK-` prefix (case-insensitive) from `{epic-id}` to get the numeric ID, then query the DB to verify it resolves to a known epic:
```bash
_epic_task_count=$(yoke db read --format lines "SELECT COUNT(*) FROM epic_tasks WHERE epic_id={epic-id}'")
```

Evaluate the result:
- If `_epic_task_count` is greater than 0: the epic is valid and has tasks — proceed to the Preflight phase.
- If `_epic_task_count` is 0: check whether the ID exists as a valid epic (query `SELECT COUNT(*) FROM items WHERE id={epic-id} AND type='epic' LIMIT 1`). If it exists (count > 0), print a soft warning and exit without error:
 > No tasks found for epic `{epic-id}` — nothing to merge.
- If neither check finds the epic: fall through to bare item ref detection below.

### Bare item ref detection (only if the epic lookup found no epic)

If the epic lookup did not find a matching epic AND `{epic-id}` looks like a bare item ref (`YOK-N` or bare numeric ID), print:

> Error: `/yoke merge` does not accept individual item refs. Use `/yoke advance YOK-N done` to complete standalone items.

If `{epic-id}` does not match any known epic and does not look like a bare item ref either, print:

> Error: `/yoke merge` is only for epic pipelines. `{epic-id}` does not match any known epic.
>
> To complete a standalone item, use: `/yoke advance YOK-N done`
