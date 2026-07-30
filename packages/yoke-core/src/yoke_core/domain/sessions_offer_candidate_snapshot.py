"""Live validation of the item snapshot carried by a scheduled candidate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from . import db_backend
from .item_ref_resolution import resolve_internal_item_id


@dataclass(frozen=True)
class CandidateSnapshotValidation:
    """Current item routing inputs and whether they match the schedule."""

    matches: bool
    status: Optional[str]
    workflow_id: Optional[str]
    workflow_version_id: Optional[int]


def revalidate_candidate_snapshot(
    conn: Any,
    *,
    item_id: Any,
    expected_status: str,
    expected_workflow_id: str,
    expected_workflow_version_id: int,
) -> CandidateSnapshotValidation:
    """Compare live status and workflow pin with one ``ScheduledStep``."""
    internal_id = resolve_internal_item_id(conn, item_id)
    if internal_id is None:
        return CandidateSnapshotValidation(False, None, None, None)
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        "SELECT status, workflow_id, workflow_version_id "
        f"FROM items WHERE id = {marker}",
        (internal_id,),
    ).fetchone()
    if row is None:
        return CandidateSnapshotValidation(False, None, None, None)
    status = str(row[0])
    workflow_id = str(row[1])
    workflow_version_id = int(row[2])
    return CandidateSnapshotValidation(
        status == str(expected_status)
        and workflow_id == str(expected_workflow_id)
        and workflow_version_id == int(expected_workflow_version_id),
        status,
        workflow_id,
        workflow_version_id,
    )


__all__ = [
    "CandidateSnapshotValidation",
    "revalidate_candidate_snapshot",
]
