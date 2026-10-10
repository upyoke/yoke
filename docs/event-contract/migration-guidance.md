# Migration Guidance

Pure-log tables are consolidated into the `events` table. Current read and write paths should use direct `events` access. If a future cutover truly needs a phased bridge, keep the compatibility view temporary and delete it as soon as callers converge. The `shepherd_verdicts` state table emits `VerdictRendered` events on write while retaining its table.

Cross-link back from [event-contract.md](../event-contract.md) for the envelope structure, registry rules, and isolation contract that govern emission paths.

## Governed log-table cutover

Read [database authority](../public/reference/agent-rules/databases.md) before
changing schema or bulk data. Declare/amend the item's DB claim, author a
permanent ordered migration, name the restore point and serving floor where
required, then rehearse through `yoke migration rehearse PREFIX-N`. Rehearse
all live universes through the model's fleet before release. Boot convergence
applies history transactionally and fail-hard; items and flows do not apply
ad hoc SQL or standalone transformation scripts.

Inside that governed history:

1. Register the event contract through its source-dev/admin owner and update
   emitters/readers against the canonical envelope and serializer.
2. Copy existing log rows into `events`, preserving original `created_at`.
   Make transformation idempotent against output already present; carry
   references to a surviving row when uniqueness requires convergence.
3. Use a temporary compatibility view only when phased readers require it.
   An old-name view replaces the table after its data and references have
   converged; it cannot be created over an existing same-name table. Preserve
   required live readers/writers and validate the actual cutover order.
4. Retire the old log table only after read/write and reference proof. Remove
   any compatibility view in later permanent history when no caller needs it.

Pure-log tables may retire; domain-state tables remain queryable authority and
emit events alongside successful state writes. The project's breakage policy
and migration strategy decide whether a phased bridge needs justification.

## Compatibility View Design

Compatibility views use a three-level COALESCE pattern to handle both the directly-inserted legacy rows and the canonical emitter envelope format. Python call sites assemble the fragment through `yoke_core.domain.sql_json.json_get`, which emits the Postgres jsonb accessor (`envelope ... #>> '{path}'`) and keeps the dialect in one file:

```python
from yoke_core.domain.sql_json import json_get

coalesce_fragment = (
    "COALESCE("
    f"{json_get('envelope', '$.context.detail.<field>')}, "  # canonical emitter format
    f"{json_get('envelope', '$.context.<field>')}, "          # alternative nesting
    f"{json_get('envelope', '$.<field>')}"                    # flat fallback
    ")"
)
```

Keep the three envelope layouts readable during the bridge; remove fallbacks
only after stored rows and callers converge.

## Domain-State Event Emission Pattern

For domain-state tables, add emission after the successful state write:

```sh
# After the state table INSERT succeeds:
yoke events emit \
 --name "<EventName>" \
 --kind workflow \
 --type "<event_type>" \
 --source-type <appropriate_source> \
 --severity INFO \
 --outcome completed \
 --item PREFIX-N \
 --context '{"state_specific_field":"value"}'
```

The state table remains the source of truth for current state. The `events` table provides the temporal log of when state changed.

## Querying the Unified Timeline

After migration, a single query answers "what happened to item X?" (Python assembles the JSON accessor through the helper; the emitted accessor is shown inline):

```python
from yoke_core.domain.sql_json import json_get

detail_expr = json_get("envelope", "$.context.detail")  # json_get emits the Postgres jsonb accessor for this path
sql = (
    f"SELECT event_name, event_type, event_kind, severity, "
    f"item_id, task_num, created_at, {detail_expr} AS detail "
    f"FROM events WHERE item_id = ? ORDER BY created_at"
)
```

This returns tool calls, status transitions, sync operations, verdicts, and phase changes -- all from one table.
