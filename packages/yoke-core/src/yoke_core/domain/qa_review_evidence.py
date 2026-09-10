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
from yoke_core.domain.qa_execution_proof import qa_evidence_run_id
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
) -> dict[str, Any]:
    """Return the artifact projection for one requirement's reviewed run.

    Resolves through :func:`qa_evidence_run_id` so a ``human_review`` verdict,
    or any run whose own capture was recorded under a different run id,
    reports the artifacts that actually back the reviewed verdict instead of
    an empty set queried straight off the reviewed run's own id.
    """
    empty = {
        "artifacts": [],
        "artifact_count": 0,
        "evidence_state": "missing",
        "evidence_summary": "No evidence artifacts are attached to this run.",
    }
    if not _table_exists(conn, "qa_runs") or not _table_exists(conn, "qa_artifacts"):
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


__all__ = ["qa_review_artifact_context"]
