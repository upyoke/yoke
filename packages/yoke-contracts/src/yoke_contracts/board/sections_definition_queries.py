"""Read current item and task definition metadata."""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from yoke_contracts.merge_queue_status import (
    LABEL_ATTEMPT_JOIN,
    LABEL_ENQUEUED_AT_SQL,
    LABEL_LANDED_AT_SQL,
)


def _items_sql(
    project_filter: str,
) -> str:
    metadata_columns = """
        (SELECT stage->>'glyph'
         FROM jsonb_array_elements(wv.definition_json::jsonb->'stages') stage
         WHERE stage->>'id'=COALESCE(i.status, 'idea') LIMIT 1),
        (SELECT stage->>'board_bucket'
         FROM jsonb_array_elements(wv.definition_json::jsonb->'stages') stage
         WHERE stage->>'id'=COALESCE(i.status, 'idea') LIMIT 1),"""
    queue_columns = f"""
        {LABEL_ENQUEUED_AT_SQL},
        {LABEL_LANDED_AT_SQL},"""
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
        i.updated_at,
        p.slug,
        p.public_item_prefix,
        i.project_sequence,{metadata_columns}{queue_columns}
        wv.definition_json::jsonb #>> '{{policies,generated_children}}'
    FROM items i
    LEFT JOIN projects p ON p.id = i.project_id
    LEFT JOIN workflow_versions wv ON wv.id = i.workflow_version_id
    {LABEL_ATTEMPT_JOIN}
    WHERE 1=1{project_filter}
    ORDER BY i.id
    """


def query_item_rows(
    db: Any,
    project_filter: str,
    params: Optional[Tuple[Any, ...]] = None,
) -> List[Tuple[Any, ...]]:
    """Read item state and pinned definition metadata."""
    enriched_sql = _items_sql(
        project_filter,
    )
    return db.query(enriched_sql, params)


def _epic_task_rows_sql() -> str:
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
    """Read per-epic task glyphs from the pinned definition."""
    enriched_sql = _epic_task_rows_sql()
    params = (epic_id,)
    rows = db.query(enriched_sql, params)
    return [
        (
            int(task_num),
            title or "",
            task_status or "",
            str(task_glyph) if task_glyph else None,
        )
        for task_num, title, task_status, task_glyph in rows
    ]


def _precomputed_epic_tasks_sql(project_filter: str) -> str:
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
    """Read batched task glyphs from pinned workflow definitions."""
    return db.query_quiet(_precomputed_epic_tasks_sql(project_filter), params)


__all__ = [
    "query_epic_task_rows",
    "query_item_rows",
    "query_precomputed_epic_task_rows",
]
