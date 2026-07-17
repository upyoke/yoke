# Migration Guidance

Pure-log tables are consolidated into the `events` table. Current read and write paths should use direct `events` access. If a future cutover truly needs a phased bridge, keep the compatibility view temporary and delete it as soon as callers converge. The `shepherd_verdicts` state table emits `VerdictRendered` events on write while retaining its table.

Cross-link back from [event-contract.md](../event-contract.md) for the envelope structure, registry rules, and isolation contract that govern emission paths.

## Migration Pattern for Future Tables

1. **Create a temporary compatibility view FIRST** when a phased read-path cutover is required. Route JSON-field extraction through the helper (`yoke_core.domain.sql_json.json_get`) from Python call sites; the SQL view body below shows the COALESCE structure, and `json_get` emits the active backend's JSON accessor (on Postgres, the jsonb path form `envelope ... #>> '{context,detail,<field>}'`).
   ```sql
   CREATE OR REPLACE VIEW <old_table> AS
   SELECT
     id,
     -- Map events columns back to the old table's column names. Python call
     -- sites should build the JSON-field accessor via
     -- `json_get("envelope", "$.context.detail.<field>")`, which emits the
     -- Postgres jsonb accessor and keeps the dialect in one file
     -- (`packages/yoke-core/src/yoke_core/domain/sql_json.py`).
     COALESCE(
       <json_get_canonical>, -- f"""{json_get("envelope", "$.context.detail.<field>")}"""
       <json_get_nested>,    -- f"""{json_get("envelope", "$.context.<field>")}"""
       <json_get_flat>       -- f"""{json_get("envelope", "$.<field>")}"""
     ) AS <old_column_name>,
     created_at
   FROM events
   WHERE event_type = '<your_event_type>';
   ```

2. **Update read paths** to query `events` directly. The compatibility view is temporary scaffolding only.

3. **Write the migration script** that inserts existing rows into `events` within a transaction, preserving original timestamps in `created_at`.

4. **Update write paths** to emit through the standard event helper instead of INSERT into the old table.

5. **Drop the old table** only after verifying the compatibility view works and all read paths are updated.
6. **Remove the temporary compatibility view** in a follow-up convergence migration once no live caller depends on it.
7. **Register the event name** in `event_registry` through the source-dev/admin registry workflow.

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

This ensures views work regardless of which code path inserted the event row, and keeps the dialect localized to one file (`sql_json.py`).

## Domain-State Event Emission Pattern

For state tables that should NOT be dropped (they serve as queryable state, not just logs), add event emission alongside the existing INSERT:

```sh
# After the state table INSERT succeeds:
yoke events emit \
 --name "<EventName>" \
 --kind workflow \
 --type "<event_type>" \
 --source-type <appropriate_source> \
 --severity INFO \
 --outcome completed \
 --item-id "<item-id>" \
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
