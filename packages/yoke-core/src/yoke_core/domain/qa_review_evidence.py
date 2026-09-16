"""Shared artifact resolution for QA review-request subject context.

The QA review producer (creation time) and the decision-request reader
(pending re-reads) both need to say what evidence backs one requirement's
reviewed run. This is the one place that answers it, so both agree.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_one, query_rows
from yoke_core.domain.deployment_qa_stage_prerequisites import (
    DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND,
)
from yoke_core.domain.qa_execution_proof import qa_evidence_run_id
from yoke_core.domain.qa_review_requirement_facts import requirement_facts
from yoke_core.domain.schema_common import _table_exists


def _row_value(row: Any, key: str) -> Any:
    if row is None:
        return None
    if isinstance(row, Mapping):
        return row.get(key)
    try:
        return row[key]
    except (IndexError, KeyError, TypeError):
        return None


def _metadata(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(str(raw or "{}"))
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def qa_review_artifact_context(
    conn: Any,
    *,
    requirement_id: int,
    run_id: int,
    expected_project_id: int | None = None,
) -> dict[str, Any]:
    """Return the artifact projection for one requirement's reviewed run.

    Resolves through :func:`qa_evidence_run_id` so a ``human_review`` verdict,
    or any run whose own capture was recorded under a different run id,
    reports the artifacts that actually back the reviewed verdict instead of
    an empty set queried straight off the reviewed run's own id.

    ``expected_project_id``, when given, must match the requirement's own
    resolved project (:func:`requirement_facts`, the same resolution the
    producer uses) -- a requirement/run pairing that is internally
    consistent but scoped to a different project than the caller expects
    refuses rather than crossing that boundary.
    """
    empty = {
        "artifacts": [],
        "artifact_count": 0,
        "evidence_state": "missing",
        "evidence_summary": "No evidence artifacts are attached to this run.",
    }
    if not _table_exists(conn, "qa_runs") or not _table_exists(conn, "qa_artifacts"):
        return empty
    if expected_project_id is not None:
        try:
            requirement = requirement_facts(conn, requirement_id)
        except (LookupError, ValueError):
            return empty
        if int(requirement["project_id"]) != int(expected_project_id):
            return empty
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    run_row = query_one(
        conn,
        "SELECT performed_by, raw_result FROM qa_runs "
        f"WHERE id={marker} AND qa_requirement_id={marker}",
        (int(run_id), int(requirement_id)),
    )
    # The reviewed run must actually belong to the named requirement, or a
    # foreign run_id/requirement_id pairing would fall through
    # qa_evidence_run_id's own fallback (which just returns run_id) and
    # surface that foreign run's artifacts as this requirement's evidence.
    if run_row is None:
        return empty
    evidence_run_id = qa_evidence_run_id(
        conn,
        requirement_id=requirement_id,
        run_id=run_id,
        performed_by=_row_value(run_row, "performed_by"),
        raw_result=_row_value(run_row, "raw_result"),
    )
    if evidence_run_id is None:
        return empty
    artifact_rows = query_rows(
        conn,
        "SELECT id, artifact_type, content_type, artifact_handle, metadata "
        f"FROM qa_artifacts WHERE qa_run_id={marker} ORDER BY id",
        (int(evidence_run_id),),
    )
    artifacts = [
        {
            "artifact_id": int(_row_value(row, "id")),
            "artifact_type": str(_row_value(row, "artifact_type")),
            "content_type": _row_value(row, "content_type"),
            "artifact_handle": _row_value(row, "artifact_handle"),
            "metadata": _metadata(_row_value(row, "metadata")),
        }
        for row in artifact_rows
    ]
    if not artifacts:
        artifacts = _covered_case_artifacts(conn, marker, requirement_id)
        if artifacts:
            kinds = sorted({artifact["artifact_type"] for artifact in artifacts})
            return {
                "artifacts": artifacts,
                "artifact_count": len(artifacts),
                "evidence_state": "attached",
                "evidence_summary": (
                    f"{len(artifacts)} artifact(s) captured by the cases this "
                    f"acceptance covers: {', '.join(kinds)}"
                ),
            }
        return empty
    artifact_kinds = sorted({artifact["artifact_type"] for artifact in artifacts})
    return {
        "artifacts": artifacts,
        "artifact_count": len(artifacts),
        "evidence_state": "attached",
        "evidence_summary": (
            f"{len(artifacts)} attached artifact(s): {', '.join(artifact_kinds)}"
        ),
    }


def _covered_case_artifacts(
    conn: Any, marker: str, requirement_id: int
) -> list[dict[str, Any]]:
    """The artifacts backing a stage acceptance, from the cases it covers.

    A stage acceptance records an aggregate verdict and captures nothing of
    its own, so reading only its own run reports "no evidence attached" on a
    stage whose cases captured screenshots — and asks a reviewer to rule on
    nothing while the pictures they need sit one join away. The cases it
    covers are the ones admitted against the same run, stage, member and
    frozen execution target: exactly the set the gate aggregated to raise
    this review.
    """
    rows = query_rows(
        conn,
        "SELECT a.id, a.artifact_type, a.content_type, a.artifact_handle, "
        "a.metadata, c.id AS requirement_id FROM qa_artifacts a "
        "JOIN qa_runs r ON r.id = a.qa_run_id "
        "JOIN qa_requirements c ON c.id = r.qa_requirement_id "
        "JOIN qa_requirements q ON q.deployment_run_id = c.deployment_run_id "
        "AND q.deployment_stage = c.deployment_stage "
        "AND COALESCE(q.deployment_member_item_id, 0) "
        "= COALESCE(c.deployment_member_item_id, 0) "
        "AND q.execution_target_digest = c.execution_target_digest "
        f"WHERE q.id = {marker} AND q.qa_kind = {marker} "
        "AND c.method_id IS NOT NULL "
        "ORDER BY a.id",
        (int(requirement_id), DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND),
    )
    return [
        {
            "artifact_id": int(_row_value(row, "id")),
            "artifact_type": str(_row_value(row, "artifact_type")),
            "content_type": _row_value(row, "content_type"),
            "artifact_handle": _row_value(row, "artifact_handle"),
            "metadata": _metadata(_row_value(row, "metadata")),
            # The case that captured it, not the acceptance that covers it.
            # Reading an artifact is authorized against its own requirement,
            # so an acceptance's borrowed evidence has to keep saying whose
            # it is or every thumbnail refuses to load.
            "requirement_id": int(_row_value(row, "requirement_id")),
        }
        for row in rows
    ]


__all__ = ["qa_review_artifact_context"]
