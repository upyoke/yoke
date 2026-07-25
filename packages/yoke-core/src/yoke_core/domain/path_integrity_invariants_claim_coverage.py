"""Catch-up invariant for workflow-required path-claim coverage.

Lives separately from :mod:`yoke_core.domain.path_integrity_invariants`
so the existing module stays under its line budget. The check is
project-scoped: every non-terminal item whose pinned workflow requires
path claims must carry a non-terminal claim or active exception.

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
from yoke_core.domain.workflow_runtime import (
    ENGINE_TERMINAL_STAGE_IDS,
    workflow_runtime_from_row,
)


INVARIANT_PATH_CLAIM_COVERAGE = "path_claim_coverage"

_NON_TERMINAL_CLAIM_STATES = ("planned", "blocked", "active")


FailureRow = Tuple[Optional[int], dict]


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def check_path_claim_coverage(
    conn: Any, project_id: int | str
) -> List[FailureRow]:
    """Return failures for non-terminal items lacking claim coverage.

    Every non-terminal item with non-optional workflow path claims must
    have a claim row or a valid exception.

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
    placeholders_claim_states = ",".join(
        p for _ in _NON_TERMINAL_CLAIM_STATES
    )
    rows = conn.execute(
        f"""
        SELECT i.id, i.status, i.workflow_id, i.workflow_version_id,
               v.version, v.definition_json, v.definition_digest
          FROM items i
          JOIN workflow_versions v ON v.id = i.workflow_version_id
         WHERE i.project_id = {p}
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
            *_NON_TERMINAL_CLAIM_STATES,
        ),
    ).fetchall()
    failures: List[FailureRow] = []
    for row in rows:
        runtime = workflow_runtime_from_row({
            "workflow_id": row[2],
            "workflow_version_id": row[3],
            "version": row[4],
            "definition_json": row[5],
            "definition_digest": row[6],
        })
        if (
            str(row[1]) in runtime.terminal_stage_ids
            or str(row[1]) in ENGINE_TERMINAL_STAGE_IDS
            or runtime.policies["path_claims"] == "optional"
        ):
            continue
        failures.append((
            int(row[0]),
            {
                "item_id": int(row[0]),
                "item_status": str(row[1]),
                "workflow_id": runtime.workflow_id,
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
