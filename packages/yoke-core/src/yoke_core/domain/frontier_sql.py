"""SQL fragments for workflow-backed frontier computation."""

#: The scan's per-item projection. The pinned workflow definition is
#: deliberately absent: it is the same handful of documents repeated once per
#: item, so ``frontier_workflow_versions`` reads it once for the whole scan and
#: the scan joins the two by ``workflow_version_id``.
FRONTIER_ITEMS_SQL_PREFIX = """
SELECT
    i.id,
    i.title,
    i.status,
    i.priority,
    i.project_id AS project,
    i.workflow_id,
    i.workflow_version_id,
    v.version AS version,
    i.frozen,
    i.blocked,
    i.blocked_reason,
    i.created_at,
    i.spec
FROM items i
JOIN workflow_versions v ON v.id = i.workflow_version_id
WHERE 1=1
"""

FRONTIER_ITEMS_SQL_SUFFIX = " ORDER BY i.id"

UNBLOCKS_COUNT_SQL = """
SELECT
    d.blocking_item_id,
    COUNT(DISTINCT d.dependent_item_id) AS unblocks
FROM item_dependencies d
WHERE d.gate_point = 'activation'
GROUP BY d.blocking_item_id
"""

__all__ = [
    "FRONTIER_ITEMS_SQL_PREFIX",
    "FRONTIER_ITEMS_SQL_SUFFIX",
    "UNBLOCKS_COUNT_SQL",
]
