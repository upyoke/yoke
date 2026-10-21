"""Persist changed render relationships using already-resolved path identities."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from yoke_core.domain.db_helpers import instant_parameter, utc_now
from yoke_core.domain.db_savepoint import savepoint
from yoke_core.domain.path_context import FAMILY_RENDER_SOURCE, FAMILY_RENDER_TARGET


def write_changed_relationships(
    conn: Any,
    relationships: Mapping[str, Sequence[str]],
    target_ids: Mapping[str, int],
    operation_id: str,
) -> int:
    """Read existing values once and upsert changed values in one statement.

    The caller resolved every id from path_targets, so repeating existence
    checks is unnecessary; the foreign key still enforces their existence.
    Unchanged values keep their original provenance and timestamp. Return the
    number of registered render targets, including those already current.
    """
    desired = {}
    target_count = 0
    for target, sources in sorted(relationships.items()):
        if target not in target_ids:
            continue
        target_count += 1
        sources = sorted({str(source) for source in sources if source})
        desired[target_ids[target], FAMILY_RENDER_TARGET, ""] = {"sources": sources}
        for source in sources:
            if source in target_ids:
                desired[target_ids[source], FAMILY_RENDER_SOURCE, target] = {
                    "target": target
                }
    if not desired:
        return 0
    existing = {
        (int(row[0]), str(row[1]), str(row[2])): json.loads(row[3])
        for row in conn.execute(
            "SELECT target_id, context_family, entry_key, value "
            "FROM path_context_values WHERE target_id = ANY(%s::bigint[]) "
            "AND context_family = ANY(%s::text[])",
            (sorted(set(target_ids.values())), [FAMILY_RENDER_TARGET, FAMILY_RENDER_SOURCE]),
        ).fetchall()
    }
    changed = [
        (*key, json.dumps(value, sort_keys=True))
        for key, value in desired.items()
        if existing.get(key) != value
    ]
    if changed:
        with savepoint(conn, "render_relationship_batch", owns=False):
            conn.execute(
                "INSERT INTO path_context_values "
                "(target_id, context_family, entry_key, value, "
                "recorded_event_id, recorded_at) "
                "SELECT v.*, %s, %s FROM "
                "unnest(%s::bigint[], %s::text[], %s::text[], %s::text[]) "
                "AS v(target_id, context_family, entry_key, value) "
                "ON CONFLICT (target_id, context_family, entry_key) DO UPDATE "
                "SET value=excluded.value, recorded_event_id=excluded.recorded_event_id, "
                "recorded_at=excluded.recorded_at "
                "WHERE path_context_values.value::jsonb IS DISTINCT FROM excluded.value::jsonb",
                (operation_id, instant_parameter(conn, utc_now()), *map(list, zip(*changed))),
            )
    return target_count
