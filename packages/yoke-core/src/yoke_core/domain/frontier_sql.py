"""SQL fragments for workflow-backed frontier computation."""

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
    v.definition_json,
    v.definition_digest,
    i.frozen,
    i.blocked,
    i.blocked_reason,
    i.created_at,
    i.spec
FROM items i
JOIN workflow_versions v ON v.id = i.workflow_version_id
WHERE i.status IN (
    'idea', 'planned', 'release',
    'blocked',
    'refining-idea', 'refined-idea',
    'implementing', 'reviewing-implementation', 'reviewed-implementation',
    'polishing-implementation', 'implemented',
    'planning', 'plan-drafted', 'refining-plan'
)
"""

FRONTIER_ITEMS_SQL_SUFFIX = " ORDER BY i.id"

UNBLOCKS_COUNT_SQL = """
SELECT
    d.blocking_item,
    COUNT(DISTINCT d.dependent_item) AS unblocks
FROM item_dependencies d
WHERE d.gate_point = 'activation'
GROUP BY d.blocking_item
"""

WIP_COUNT_SQL_PREFIX = """
SELECT COUNT(*) FROM items
WHERE status IN ('implementing', 'reviewing-implementation')
"""

__all__ = [
    "FRONTIER_ITEMS_SQL_PREFIX",
    "FRONTIER_ITEMS_SQL_SUFFIX",
    "UNBLOCKS_COUNT_SQL",
    "WIP_COUNT_SQL_PREFIX",
]
