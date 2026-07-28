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

import json
from typing import Any, List, Optional, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.workflow_effective_policies import (
    resolve_effective_workflow_policies,
)
from yoke_core.domain.workflow_runtime import ENGINE_TERMINAL_STAGE_IDS, workflow_runtime_from_row


INVARIANT_PATH_CLAIM_COVERAGE = "path_claim_coverage"

FailureRow = Tuple[Optional[int], dict]


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def check_path_claim_coverage(conn: Any, project_id: int | str) -> List[FailureRow]:
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
    rows = conn.execute(
        f"""
        SELECT i.id, i.status, i.workflow_id, i.workflow_version_id,
               v.version, v.definition_json, v.definition_digest,
               i.workflow_posture
          FROM items i
          JOIN workflow_versions v ON v.id = i.workflow_version_id
         WHERE i.project_id = {p}
        ORDER BY i.id
        """,
        (resolved_project_id,),
    ).fetchall()
    failures: List[FailureRow] = []
    for row in rows:
        runtime = workflow_runtime_from_row(
            {
                "workflow_id": row[2],
                "workflow_version_id": row[3],
                "version": row[4],
                "definition_json": row[5],
                "definition_digest": row[6],
            }
        )
        effective = resolve_effective_workflow_policies(
            runtime,
            json.loads(str(row[7] or "{}")),
        )
        if (
            str(row[1]) in runtime.terminal_stage_ids
            or str(row[1]) in ENGINE_TERMINAL_STAGE_IDS
            or not effective.requires_path_claims
        ):
            continue
        from yoke_core.domain.path_claim_required_gate import evaluate

        gate = evaluate(conn, int(row[0]))
        if gate["verdict"] == "pass":
            continue
        reason = str(gate["reason"])
        failures.append(
            (
                int(row[0]),
                {
                    "item_id": int(row[0]),
                    "item_status": str(row[1]),
                    "workflow_id": runtime.workflow_id,
                    "reason": (reason),
                },
            )
        )
    return failures


__all__ = [
    "INVARIANT_PATH_CLAIM_COVERAGE",
    "check_path_claim_coverage",
]
