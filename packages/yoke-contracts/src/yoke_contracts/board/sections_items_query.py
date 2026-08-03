"""Item-row query compatibility for board data record/replay cutovers."""

from __future__ import annotations

from typing import Any, List, Tuple


def _items_sql(project_filter: str, *, definition_metadata: bool) -> str:
    metadata_columns = ""
    if definition_metadata:
        metadata_columns = """
        (SELECT stage->>'glyph'
         FROM jsonb_array_elements(wv.definition_json::jsonb->'stages') stage
         WHERE stage->>'id'=COALESCE(i.status, 'idea') LIMIT 1),
        (SELECT stage->>'board_bucket'
         FROM jsonb_array_elements(wv.definition_json::jsonb->'stages') stage
         WHERE stage->>'id'=COALESCE(i.status, 'idea') LIMIT 1),"""
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
        wv.definition_json::jsonb #>> '{{policies,generated_children}}'
    FROM items i
    LEFT JOIN projects p ON p.id = i.project_id
    LEFT JOIN workflow_versions wv ON wv.id = i.workflow_version_id
    WHERE 1=1{project_filter}
    ORDER BY i.id
    """


def query_item_rows(db: Any, project_filter: str) -> List[Tuple[Any, ...]]:
    """Read definition metadata, with exact fallback for older payloads."""
    enriched_sql = _items_sql(project_filter, definition_metadata=True)
    has_query = getattr(db, "has_query", None)
    if not callable(has_query) or has_query(enriched_sql):
        return db.query(enriched_sql)

    legacy_sql = _items_sql(project_filter, definition_metadata=False)
    rows = db.query(legacy_sql)
    return [(*row[:-1], None, None, row[-1]) for row in rows]


__all__ = ["query_item_rows"]
