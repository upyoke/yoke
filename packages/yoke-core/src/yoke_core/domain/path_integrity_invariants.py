"""Path-integrity invariant check functions.

Each check returns ``(target_id, details)`` failures over recorded
substrate only; invariants never read live git state.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple


from yoke_core.domain import db_backend
from yoke_core.domain.path_integrity_invariants_claim_coverage import (
    INVARIANT_PATH_CLAIM_COVERAGE,
    check_path_claim_coverage,
)
from yoke_core.domain.path_integrity_invariants_render_relationship import (
    INVARIANT_RENDER_RELATIONSHIP,
    check_render_relationship,
)


INVARIANT_DUPLICATE_IDENTITY = "duplicate_identity"
INVARIANT_PARENT_CHILD = "parent_child_coherence"
INVARIANT_SNAPSHOT_IDEMPOTENCY = "snapshot_idempotency"
INVARIANT_CONTINUITY_DETERMINISM = "continuity_determinism"
INVARIANT_CONTEXT_INHERITANCE = "context_inheritance"
INVARIANT_DRIFT = "drift"

ALL_INVARIANTS: Tuple[str, ...] = (
    INVARIANT_DUPLICATE_IDENTITY,
    INVARIANT_PARENT_CHILD,
    INVARIANT_SNAPSHOT_IDEMPOTENCY,
    INVARIANT_CONTINUITY_DETERMINISM,
    INVARIANT_CONTEXT_INHERITANCE,
    INVARIANT_DRIFT,
    INVARIANT_PATH_CLAIM_COVERAGE,
    INVARIANT_RENDER_RELATIONSHIP,
)


FailureRow = Tuple[Optional[int], dict]


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def check_duplicate_identity(
    conn: Any, project_id: str
) -> List[FailureRow]:
    p = _p(conn)
    rows = conn.execute(
        "SELECT path_string, generation, COUNT(*) AS n, "
        "       STRING_AGG(id::text, ',') AS ids "
        "FROM path_targets "
        f"WHERE project_id={p} "
        "GROUP BY path_string, generation HAVING COUNT(*) > 1",
        (project_id,),
    ).fetchall()
    failures: List[FailureRow] = []
    for r in rows:
        ids = [int(x) for x in str(r[3]).split(",")]
        failures.append((
            ids[0],
            {
                "path_string": str(r[0]),
                "generation": int(r[1]),
                "count": int(r[2]),
                "target_ids": ids,
            },
        ))
    return failures


def check_parent_child(
    conn: Any, project_id: str
) -> List[FailureRow]:
    p = _p(conn)
    rows = conn.execute(
        "SELECT c.id AS child_id, c.parent_target_id AS parent_id, "
        "       p.project_id AS parent_project "
        "FROM path_targets c "
        "JOIN path_targets p ON p.id = c.parent_target_id "
        f"WHERE c.project_id={p} AND p.project_id <> c.project_id",
        (project_id,),
    ).fetchall()
    failures: List[FailureRow] = []
    for r in rows:
        failures.append((
            int(r[0]),
            {
                "child_id": int(r[0]),
                "parent_id": int(r[1]),
                "child_project": project_id,
                "parent_project": str(r[2]),
            },
        ))
    return failures


def check_snapshot_idempotency(
    conn: Any, project_id: str
) -> List[FailureRow]:
    p = _p(conn)
    duplicate_rows = conn.execute(
        "SELECT commit_sha, STRING_AGG(id::text, ',') AS ids, COUNT(*) AS n "
        f"FROM path_snapshots WHERE project_id={p} "
        "GROUP BY commit_sha HAVING COUNT(*) > 1",
        (project_id,),
    ).fetchall()
    failures: List[FailureRow] = []
    for r in duplicate_rows:
        snap_ids = [int(x) for x in str(r[1]).split(",")]
        sets: List[frozenset] = []
        for sid in snap_ids:
            entries = conn.execute(
                "SELECT target_id FROM path_snapshot_entries "
                f"WHERE snapshot_id={p} ORDER BY target_id",
                (sid,),
            ).fetchall()
            sets.append(frozenset(int(e[0]) for e in entries))
        canonical = sets[0]
        if any(s != canonical for s in sets[1:]):
            failures.append((
                None,
                {
                    "commit_sha": str(r[0]),
                    "snapshot_ids": snap_ids,
                    "entry_set_sizes": [len(s) for s in sets],
                },
            ))
    return failures


def check_continuity_determinism(
    conn: Any, project_id: str
) -> List[FailureRow]:
    p = _p(conn)
    duplicate_rows = conn.execute(
        "SELECT m.before_target_id, "
        "       COUNT(DISTINCT m.after_target_id) AS distinct_after, "
        "       STRING_AGG(DISTINCT m.after_target_id::text, ',') AS afters "
        "FROM path_moves m "
        "JOIN path_targets t ON t.id = m.before_target_id "
        f"WHERE t.project_id={p} "
        "GROUP BY m.before_target_id "
        "HAVING COUNT(DISTINCT m.after_target_id) > 1",
        (project_id,),
    ).fetchall()
    failures: List[FailureRow] = []
    for r in duplicate_rows:
        afters = [int(x) for x in str(r[2]).split(",")]
        failures.append((
            int(r[0]),
            {
                "before_target_id": int(r[0]),
                "after_target_ids": afters,
                "distinct_after_count": int(r[1]),
            },
        ))

    cross_project_rows = conn.execute(
        "SELECT m.before_target_id, m.after_target_id, "
        "       b.project_id AS before_project, "
        "       a.project_id AS after_project "
        "FROM path_moves m "
        "JOIN path_targets b ON b.id = m.before_target_id "
        "JOIN path_targets a ON a.id = m.after_target_id "
        f"WHERE b.project_id={p} AND a.project_id <> b.project_id",
        (project_id,),
    ).fetchall()
    for r in cross_project_rows:
        failures.append((
            int(r[0]),
            {
                "before_target_id": int(r[0]),
                "after_target_id": int(r[1]),
                "before_project": str(r[2]),
                "after_project": str(r[3]),
            },
        ))
    return failures


def check_context_inheritance(
    conn: Any, project_id: str
) -> List[FailureRow]:
    """Detect conflicting inherited context across continuity moves."""
    p = _p(conn)
    rows = conn.execute(
        f"""
        WITH RECURSIVE move_context(
            after_target_id,
            source_target_id,
            context_target_id,
            depth
        ) AS (
            SELECT m.after_target_id,
                   m.before_target_id,
                   m.before_target_id,
                   0
              FROM path_moves m
              JOIN path_targets b ON b.id = m.before_target_id
              JOIN path_targets a ON a.id = m.after_target_id
             WHERE b.project_id = {p}
               AND a.project_id = b.project_id
            UNION ALL
            SELECT mc.after_target_id,
                   mc.source_target_id,
                   t.parent_target_id,
                   mc.depth + 1
              FROM move_context mc
              JOIN path_targets t ON t.id = mc.context_target_id
             WHERE t.parent_target_id IS NOT NULL
        ),
        ctx AS (
            SELECT mc.after_target_id,
                   mc.source_target_id,
                   mc.context_target_id,
                   mc.depth,
                   cv.context_family,
                   cv.entry_key,
                   cv.value
              FROM move_context mc
              JOIN path_context_values cv
                ON cv.target_id = mc.context_target_id
        ),
        nearest AS (
            SELECT after_target_id,
                   source_target_id,
                   context_family,
                   entry_key,
                   MIN(depth) AS nearest_depth
              FROM ctx
             GROUP BY after_target_id, source_target_id,
                      context_family, entry_key
        )
        SELECT ctx.after_target_id,
               ctx.context_family,
               ctx.entry_key,
               COUNT(DISTINCT ctx.value) AS value_count,
               STRING_AGG(DISTINCT ctx.source_target_id::text, ',') AS sources,
               STRING_AGG(DISTINCT ctx.context_target_id::text, ',') AS providers,
               STRING_AGG(DISTINCT ctx.value, ',') AS context_values
          FROM ctx
          JOIN nearest n
            ON n.after_target_id = ctx.after_target_id
           AND n.source_target_id = ctx.source_target_id
           AND n.context_family = ctx.context_family
           AND n.entry_key = ctx.entry_key
           AND n.nearest_depth = ctx.depth
         GROUP BY ctx.after_target_id, ctx.context_family, ctx.entry_key
        HAVING COUNT(DISTINCT ctx.value) > 1
        """,
        (project_id,),
    ).fetchall()
    failures: List[FailureRow] = []
    for r in rows:
        failures.append((
            int(r[0]),
            {
                "after_target_id": int(r[0]),
                "context_family": str(r[1]),
                "entry_key": str(r[2]),
                "value_count": int(r[3]),
                "source_target_ids": [
                    int(x) for x in str(r[4]).split(",") if x
                ],
                "context_provider_ids": [
                    int(x) for x in str(r[5]).split(",") if x
                ],
                "conflicting_values": str(r[6]),
            },
        ))
    return failures


def check_drift(
    conn: Any, project_id: str
) -> List[FailureRow]:
    """Detect snapshot-to-target drift inside the recorded substrate."""
    p = _p(conn)
    rows = conn.execute(
        f"""
        SELECT s.id, e.target_id, t.project_id
        FROM path_snapshots s
        JOIN path_snapshot_entries e ON e.snapshot_id = s.id
        JOIN path_targets t ON t.id = e.target_id
        WHERE s.project_id = {p} AND t.project_id <> s.project_id
        """,
        (project_id,),
    ).fetchall()
    failures: List[FailureRow] = []
    for r in rows:
        failures.append((
            int(r[1]),
            {
                "snapshot_id": int(r[0]),
                "target_id": int(r[1]),
                "snapshot_project": project_id,
                "target_project": str(r[2]),
            },
        ))
    return failures


INVARIANT_FUNCS: Tuple[Tuple[str, object], ...] = (
    (INVARIANT_DUPLICATE_IDENTITY, check_duplicate_identity),
    (INVARIANT_PARENT_CHILD, check_parent_child),
    (INVARIANT_SNAPSHOT_IDEMPOTENCY, check_snapshot_idempotency),
    (INVARIANT_CONTINUITY_DETERMINISM, check_continuity_determinism),
    (INVARIANT_CONTEXT_INHERITANCE, check_context_inheritance),
    (INVARIANT_DRIFT, check_drift),
    (INVARIANT_PATH_CLAIM_COVERAGE, check_path_claim_coverage),
    (INVARIANT_RENDER_RELATIONSHIP, check_render_relationship),
)


__all__ = [
    "ALL_INVARIANTS",
    "INVARIANT_CONTEXT_INHERITANCE",
    "INVARIANT_CONTINUITY_DETERMINISM",
    "INVARIANT_DRIFT",
    "INVARIANT_DUPLICATE_IDENTITY",
    "INVARIANT_FUNCS",
    "INVARIANT_PARENT_CHILD",
    "INVARIANT_PATH_CLAIM_COVERAGE",
    "INVARIANT_RENDER_RELATIONSHIP",
    "INVARIANT_SNAPSHOT_IDEMPOTENCY",
    "check_context_inheritance",
    "check_continuity_determinism",
    "check_drift",
    "check_duplicate_identity",
    "check_parent_child",
    "check_path_claim_coverage",
    "check_render_relationship",
    "check_snapshot_idempotency",
]
