"""Path context recording (path continuity layer ``path_context_values`` writers and reads).

A ``path_context_values`` row attaches family-keyed durable operating
truth to a ``path_targets`` row. Two families open the table:

* ``posture`` - per-path facts like "criticality=high", "is_generated",
  "is_lock_sensitive". ``entry_key`` is the rule kind
  (``criticality``, ``generated``, ``lock_sensitive``, ...).
* ``doc_link`` - per-path documentation pointers ("agents_root",
  "claude_rules", "docs_tree", ...). ``entry_key`` is the link role.

Future consumers add more families without schema migration; the table
itself does not enforce the family vocabulary.

Writes are authored truth: every row carries a non-empty
``recorded_event_id`` provenance string naming the event that recorded
or migrated the value. The string is opaque — the writer does
NOT verify it against the events ledger, because severity retention
prunes ledger rows on a schedule the durable context rows outlive
(decision record: ``docs/archive/decisions/path-provenance-event-fk.md``).
The writer still refuses heuristic-only signal - there is no
inference-from-git authoring path here.

Reads resolve nearest-ancestor inheritance through
``path_targets.parent_target_id``. When two ancestors at the
same depth carry conflicting values for the same family/key, the read
raises :class:`PathContextConflictError` instead of silently picking a
winner.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now


FAMILY_POSTURE = "posture"
FAMILY_DOC_LINK = "doc_link"

# Architecture-fitness families (architecture-fitness). Each row carries one fact;
# inheritance through ``path_targets.parent_target_id`` keeps the live
# tree shallow — directory-level assignments cascade to descendants and
# the exemption families excuse whole subtrees in one row.
FAMILY_ARCHITECTURE_LAYER = "architecture_layer"
FAMILY_ARCHITECTURE_DOMAIN = "architecture_domain"
FAMILY_DEPENDENCY_RULE = "architecture_dependency_rule"
FAMILY_CROSS_CUTTING_ENTRYPOINT = "architecture_cross_cutting_entrypoint"
FAMILY_GENERATED = "architecture_generated"
FAMILY_FIXTURE = "architecture_fixture"
FAMILY_ARCHIVE = "architecture_archive"
FAMILY_TEST_SURFACE = "architecture_test_surface"
FAMILY_TEMPLATE_MANAGED = "architecture_template_managed"

# Render-relationship families. The overlap classifier consults these
# to distinguish false-positive overlap on deterministic rendered outputs
# from real coordination on the underlying seed sources.
FAMILY_RENDER_TARGET = "render_target"
FAMILY_RENDER_SOURCE = "render_source"

ARCHITECTURE_CLASSIFICATION_FAMILIES = frozenset({
    FAMILY_ARCHITECTURE_LAYER,
    FAMILY_ARCHITECTURE_DOMAIN,
    FAMILY_DEPENDENCY_RULE,
    FAMILY_CROSS_CUTTING_ENTRYPOINT,
})

ARCHITECTURE_EXEMPTION_FAMILIES = frozenset({
    FAMILY_GENERATED,
    FAMILY_FIXTURE,
    FAMILY_ARCHIVE,
    FAMILY_TEST_SURFACE,
    FAMILY_TEMPLATE_MANAGED,
})

ARCHITECTURE_FAMILIES = (
    ARCHITECTURE_CLASSIFICATION_FAMILIES
    | ARCHITECTURE_EXEMPTION_FAMILIES
)

RENDER_RELATIONSHIP_FAMILIES = frozenset({
    FAMILY_RENDER_TARGET,
    FAMILY_RENDER_SOURCE,
})

# Open family vocabulary; additions land alongside their consumers.
KNOWN_FAMILIES = frozenset(
    {FAMILY_POSTURE, FAMILY_DOC_LINK}
    | ARCHITECTURE_FAMILIES
    | RENDER_RELATIONSHIP_FAMILIES
)


class PathContextError(Exception):
    """Raised when context authoring cannot proceed."""


class PathContextConflictError(PathContextError):
    """Raised when nearest-ancestor inheritance encounters a same-depth tie.

    Conflicting values for the same family/key at the same depth in the
    parent chain are an error, not a silent winner.
    """


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _verify_provenance_string(event_id: Any) -> None:
    if not isinstance(event_id, str) or not event_id.strip():
        raise PathContextError(
            "recorded_event_id must be a non-empty provenance string; "
            "context authoring requires a recorded provenance event id"
        )


def _verify_target_exists(conn: Any, target_id: int) -> None:
    p = _p(conn)
    row = conn.execute(
        f"SELECT 1 FROM path_targets WHERE id = {p}", (target_id,),
    ).fetchone()
    if row is None:
        raise PathContextError(
            f"target_id={target_id} not found in path_targets"
        )


def put_context_value(
    conn: Any,
    *,
    target_id: int,
    context_family: str,
    entry_key: str,
    value: Dict[str, Any],
    recorded_event_id: str,
) -> int:
    """Insert or replace a context value row.

    ``entry_key`` is the keyed-set key for keyed families and the
    empty string for singleton families. The (target_id,
    context_family, entry_key) UNIQUE constraint ensures one row per
    identity; re-authoring the same identity overwrites the value and
    bumps ``recorded_event_id`` / ``recorded_at``.

    Returns the row's ``id``. Provenance is mandatory; the writer
    refuses without a non-empty ``recorded_event_id`` string (opaque —
    not verified against the retention-pruned events ledger).
    """
    if not isinstance(value, dict):
        raise PathContextError(
            f"value must be a JSON object (got {type(value).__name__})"
        )
    if not isinstance(context_family, str) or not context_family:
        raise PathContextError("context_family must be a non-empty string")
    if entry_key is None:
        raise PathContextError("entry_key must be a string (use '' for singleton)")
    if not isinstance(entry_key, str):
        raise PathContextError(
            f"entry_key must be a string (got {type(entry_key).__name__})"
        )

    _verify_target_exists(conn, target_id)
    _verify_provenance_string(recorded_event_id)

    payload = json.dumps(value, sort_keys=True)
    now = iso8601_now()
    p = _p(conn)
    existing = conn.execute(
        "SELECT id FROM path_context_values "
        f"WHERE target_id={p} AND context_family={p} AND entry_key={p}",
        (target_id, context_family, entry_key),
    ).fetchone()
    if existing is None:
        cur = conn.execute(
        "INSERT INTO path_context_values "
        "(target_id, context_family, entry_key, value, "
        " recorded_event_id, recorded_at) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}) RETURNING id",
        (target_id, context_family, entry_key, payload,
             recorded_event_id, now),
        )
        return int(cur.fetchone()[0])
    row_id = int(existing[0])
    conn.execute(
        "UPDATE path_context_values "
        f"SET value={p}, recorded_event_id={p}, recorded_at={p} "
        f"WHERE id={p}",
        (payload, recorded_event_id, now, row_id),
    )
    return row_id


def _ancestor_chain(
    conn: Any, target_id: int,
) -> List[Tuple[int, int]]:
    """Return [(target_id, depth)] for *target_id* and every ancestor.

    Depth 0 is the target itself; depth grows toward the root. Order
    is nearest-first (shallow depth first).
    """
    p = _p(conn)
    rows = conn.execute(
        f"""
        WITH RECURSIVE chain(id, parent_target_id, depth) AS (
            SELECT id, parent_target_id, 0
              FROM path_targets WHERE id = {p}
            UNION ALL
            SELECT t.id, t.parent_target_id, c.depth + 1
              FROM path_targets t
              JOIN chain c ON t.id = c.parent_target_id
        )
        SELECT id, depth FROM chain ORDER BY depth
        """,
        (target_id,),
    ).fetchall()
    return [(int(r[0]), int(r[1])) for r in rows]


def read_context_value(
    conn: Any,
    *,
    target_id: int,
    context_family: str,
    entry_key: str,
) -> Optional[Dict[str, Any]]:
    """Return the inherited context value for (family, entry_key).

    Resolves through the parent chain nearest-first. The first depth
    that carries one or more matching rows is the resolution depth.
    If exactly one row exists at that depth, its value is returned.
    If two or more conflicting rows exist at the same depth (different
    parent ancestors at equal distance), :class:`PathContextConflictError`
    is raised; the read refuses to pick a silent winner.

    Returns ``None`` when no ancestor in the chain carries a value.
    """
    if not isinstance(context_family, str) or not context_family:
        raise PathContextError("context_family must be a non-empty string")
    if not isinstance(entry_key, str):
        raise PathContextError("entry_key must be a string")

    chain = _ancestor_chain(conn, target_id)
    if not chain:
        return None

    # Group by depth; for each depth bucket, collect rows from path_context_values.
    by_depth: Dict[int, List[Tuple[int, str]]] = {}
    target_ids_by_depth: Dict[int, List[int]] = {}
    for tid, depth in chain:
        target_ids_by_depth.setdefault(depth, []).append(tid)

    for depth in sorted(target_ids_by_depth):
        ids = target_ids_by_depth[depth]
        p = _p(conn)
        placeholders = ",".join(p for _ in ids)
        rows = conn.execute(
            f"SELECT target_id, value FROM path_context_values "
            f"WHERE context_family={p} AND entry_key={p} "
            f"AND target_id IN ({placeholders})",
            (context_family, entry_key, *ids),
        ).fetchall()
        if not rows:
            continue
        if len(rows) == 1:
            value_text = rows[0][1] if not hasattr(rows[0], "keys") else rows[0]["value"]
            try:
                return json.loads(value_text or "{}")
            except (TypeError, ValueError):
                return {}
        distinct_values = {
            (r[1] if not hasattr(r, "keys") else r["value"])
            for r in rows
        }
        if len(distinct_values) == 1:
            value_text = next(iter(distinct_values))
            try:
                return json.loads(value_text or "{}")
            except (TypeError, ValueError):
                return {}
        raise PathContextConflictError(
            f"same-depth conflict resolving {context_family}/{entry_key} "
            f"for target_id={target_id} at depth={depth}: "
            f"{len(rows)} rows with different values"
        )
    return None


__all__ = [
    "ARCHITECTURE_CLASSIFICATION_FAMILIES",
    "ARCHITECTURE_EXEMPTION_FAMILIES",
    "ARCHITECTURE_FAMILIES",
    "FAMILY_ARCHITECTURE_DOMAIN",
    "FAMILY_ARCHITECTURE_LAYER",
    "FAMILY_ARCHIVE",
    "FAMILY_CROSS_CUTTING_ENTRYPOINT",
    "FAMILY_DEPENDENCY_RULE",
    "FAMILY_DOC_LINK",
    "FAMILY_FIXTURE",
    "FAMILY_GENERATED",
    "FAMILY_POSTURE",
    "FAMILY_RENDER_SOURCE",
    "FAMILY_RENDER_TARGET",
    "FAMILY_TEMPLATE_MANAGED",
    "FAMILY_TEST_SURFACE",
    "KNOWN_FAMILIES",
    "PathContextConflictError",
    "PathContextError",
    "RENDER_RELATIONSHIP_FAMILIES",
    "put_context_value",
    "read_context_value",
]
