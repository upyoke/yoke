"""Catch-up invariant for path-claim coverage on non-terminal items.

Lives separately from :mod:`yoke_core.domain.path_integrity_invariants`
so the existing module stays under its line budget. The check is
type-gated and project-scoped: every non-terminal ``issue`` / ``epic``
item belonging to ``project_id`` must carry at least one non-terminal
path claim OR an active no-claim exception.

The invariant is generic by design (Required Behavior #7): no item id
is hardcoded. the spec's test case — is caught by the
generic rule when it has no claim row, and likewise for any other
non-terminal item that drifted into the system before the
claim-required gate landed.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.schema_common import _table_exists


INVARIANT_PATH_CLAIM_COVERAGE = "path_claim_coverage"

_NON_TERMINAL_ITEM_STATUSES = (
    "idea",
    "refining-idea",
    "refined-idea",
    "planning",
    "plan-drafted",
    "refining-plan",
    "planned",
    "implementing",
    "reviewing-implementation",
    "reviewed-implementation",
    "polishing-implementation",
    "implemented",
    "release",
    "blocked",
    "stopped",
)

_COVERED_ITEM_TYPES = ("issue", "epic")

_NON_TERMINAL_CLAIM_STATES = ("planned", "blocked", "active")


FailureRow = Tuple[Optional[int], dict]


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def check_path_claim_coverage(
    conn: Any, project_id: int | str
) -> List[FailureRow]:
    """Return failures for non-terminal items lacking claim coverage.

    Every issue/epic item in a non-terminal status must have at least
    one non-terminal claim row OR a non-terminal mode='exception' row
    with non-empty ``exception_reason``. A failure surfaces the
    item id, status, type, and reason so the operator can amend the
    item without re-querying.

    Self-skips when the path_claims / items tables are absent — the
    path-integrity verifier runs against tiny synthetic substrates in
    its own tests, and missing optional tables are not invariant
    failures.
    """
    required_tables = {"items", "path_claims", "path_claim_targets"}
    if not all(_table_exists(conn, table) for table in required_tables):
        return []
    resolved_project_id = resolve_project_id(conn, project_id)
    p = _p(conn)
    placeholders_status = ",".join(p for _ in _NON_TERMINAL_ITEM_STATUSES)
    placeholders_type = ",".join(p for _ in _COVERED_ITEM_TYPES)
    placeholders_claim_states = ",".join(
        p for _ in _NON_TERMINAL_CLAIM_STATES
    )
    rows = conn.execute(
        f"""
        SELECT i.id, i.status, i.type
          FROM items i
         WHERE i.project_id = {p}
           AND i.status IN ({placeholders_status})
           AND i.type IN ({placeholders_type})
           AND NOT EXISTS (
               SELECT 1
                 FROM path_claims pc
                WHERE pc.item_id = i.id
                  AND pc.state IN ({placeholders_claim_states})
                  AND (
                      (
                          pc.mode <> 'exception'
                          AND EXISTS (
                              SELECT 1
                                FROM path_claim_targets pct
                               WHERE pct.claim_id = pc.id
                          )
                      )
                      OR (
                          pc.mode = 'exception'
                          AND COALESCE(TRIM(pc.exception_reason), '') <> ''
                      )
                  )
           )
        ORDER BY i.id
        """,
        (
            resolved_project_id,
            *_NON_TERMINAL_ITEM_STATUSES,
            *_COVERED_ITEM_TYPES,
            *_NON_TERMINAL_CLAIM_STATES,
        ),
    ).fetchall()
    failures: List[FailureRow] = []
    for row in rows:
        failures.append((
            int(row[0]),
            {
                "item_id": int(row[0]),
                "item_status": str(row[1]),
                "item_type": str(row[2]),
                "reason": (
                    "non-terminal item lacks any non-terminal path claim or "
                    "active no-claim exception"
                ),
            },
        ))
    return failures


__all__ = [
    "INVARIANT_PATH_CLAIM_COVERAGE",
    "check_path_claim_coverage",
]
