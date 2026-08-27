"""Definition-metadata queries with record/replay rollout compatibility."""

from __future__ import annotations

from typing import Any, List, Optional, Tuple


def _items_sql(
    project_filter: str,
    *,
    definition_metadata: bool,
    queue_metadata: bool,
) -> str:
    metadata_columns = ""
    if definition_metadata:
        metadata_columns = """
        (SELECT stage->>'glyph'
         FROM jsonb_array_elements(wv.definition_json::jsonb->'stages') stage
         WHERE stage->>'id'=COALESCE(i.status, 'idea') LIMIT 1),
        (SELECT stage->>'board_bucket'
         FROM jsonb_array_elements(wv.definition_json::jsonb->'stages') stage
         WHERE stage->>'id'=COALESCE(i.status, 'idea') LIMIT 1),"""
    queue_columns = ""
    if queue_metadata:
        queue_columns = ", i.merge_queue_enqueued_at, i.merge_queue_landed_at"
    return f"""
    SELECT
        i.id,
        REPLACE(i.title, '|', '∣'),
        i.workflow_id,
        COALESCE(i.status, 'idea'),
        COALESCE(i.priority, 'medium'),
        CASE WHEN i.frozen = 1 THEN 1 ELSE 0 END,
        CASE WHEN i.blocked = 1 THEN 1 ELSE 0 END,
        i.id,
        CASE WHEN p.emoji IS NOT NULL AND p.emoji <> ''
             THEN p.emoji || ' ' || p.slug
             ELSE p.slug END,
        COALESCE(i.updated_at, ''),
        p.slug,
        p.public_item_prefix,
        i.project_sequence,{metadata_columns}
        wv.definition_json::jsonb #>> '{{policies,generated_children}}'{queue_columns}
    FROM items i
    LEFT JOIN projects p ON p.id = i.project_id
    LEFT JOIN workflow_versions wv ON wv.id = i.workflow_version_id
    WHERE 1=1{project_filter}
    ORDER BY i.id
    """


def query_item_rows(
    db: Any,
    project_filter: str,
    params: Optional[Tuple[Any, ...]] = None,
) -> List[Tuple[Any, ...]]:
    """Read item definition metadata, falling back for older payloads."""
    enriched_sql = _items_sql(
        project_filter,
        definition_metadata=True,
        queue_metadata=True,
    )
    has_query = getattr(db, "has_query", None)
    if not callable(has_query) or has_query(enriched_sql, params):
        return db.query(enriched_sql, params)

    prior_sql = _items_sql(
        project_filter,
        definition_metadata=True,
        queue_metadata=False,
    )
    if has_query(prior_sql, params):
        return [(*row, "", "") for row in db.query(prior_sql, params)]

    legacy_sql = _items_sql(
        project_filter,
        definition_metadata=False,
        queue_metadata=False,
    )
    return [
        (*row[:-1], None, None, row[-1], "", "") for row in db.query(legacy_sql, params)
    ]


def _epic_task_rows_sql(*, definition_metadata: bool) -> str:
    if not definition_metadata:
        return (
            "SELECT task_num, title, status FROM epic_tasks "
            "WHERE epic_id = %s ORDER BY task_num"
        )
    return (
        "SELECT et.task_num, et.title, et.status, "
        "(SELECT stage->>'glyph' "
        " FROM jsonb_array_elements(wv.definition_json::jsonb->'stages') stage "
        " WHERE stage->>'id'=et.status LIMIT 1) "
        "FROM epic_tasks et "
        "LEFT JOIN items i ON i.id = et.epic_id "
        "LEFT JOIN workflow_versions wv ON wv.id = i.workflow_version_id "
        "WHERE et.epic_id = %s ORDER BY et.task_num"
    )


def query_epic_task_rows(
    db: Any, epic_id: int
) -> List[Tuple[int, str, str, Optional[str]]]:
    """Read per-epic task glyphs with an exact legacy-query fallback."""
    enriched_sql = _epic_task_rows_sql(definition_metadata=True)
    params = (epic_id,)
    has_query = getattr(db, "has_query", None)
    if not callable(has_query) or has_query(enriched_sql, params):
        rows = db.query(enriched_sql, params)
    else:
        legacy_sql = _epic_task_rows_sql(definition_metadata=False)
        rows = [(*row, None) for row in db.query(legacy_sql, params)]
    return [
        (
            int(task_num),
            title or "",
            task_status or "",
            str(task_glyph) if task_glyph else None,
        )
        for task_num, title, task_status, task_glyph in rows
    ]


def _precomputed_epic_tasks_sql(
    project_filter: str, *, definition_metadata: bool
) -> str:
    metadata_column = ""
    workflow_join = ""
    if definition_metadata:
        metadata_column = """,
               (SELECT stage->>'glyph'
                FROM jsonb_array_elements(wv.definition_json::jsonb->'stages') stage
                WHERE stage->>'id'=et.status LIMIT 1)"""
        workflow_join = (
            "\n        LEFT JOIN workflow_versions wv ON wv.id = i.workflow_version_id"
        )
    return f"""
        SELECT et.epic_id, et.task_num, et.title, et.status{metadata_column}
        FROM epic_tasks et
        JOIN items i ON i.id = et.epic_id{workflow_join}
        WHERE 1=1{project_filter}
        ORDER BY et.epic_id, et.task_num
        """


def query_precomputed_epic_task_rows(
    db: Any,
    project_filter: str,
    params: Optional[Tuple[Any, ...]] = None,
) -> List[Tuple[Any, ...]]:
    """Read batched task glyphs with an exact legacy-query fallback."""
    enriched_sql = _precomputed_epic_tasks_sql(
        project_filter,
        definition_metadata=True,
    )
    has_query_quiet = getattr(db, "has_query_quiet", None)
    if not callable(has_query_quiet) or has_query_quiet(enriched_sql, params):
        return db.query_quiet(enriched_sql, params)
    legacy_sql = _precomputed_epic_tasks_sql(
        project_filter,
        definition_metadata=False,
    )
    return [(*row, None) for row in db.query_quiet(legacy_sql, params)]


__all__ = [
    "query_epic_task_rows",
    "query_item_rows",
    "query_precomputed_epic_task_rows",
]
