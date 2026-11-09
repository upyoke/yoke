"""Snapshot identity and missing-inventory refusal for architecture readers."""

from __future__ import annotations

from typing import Any

from yoke_contracts.refusal_recovery import compose_refusal
from yoke_core.domain import db_backend
from yoke_core.domain.path_snapshot_content_rows import newest_content_snapshot_id


class ArchitectureSnapshotUnavailable(ValueError):
    """Architecture cannot be evaluated without a stored file inventory."""

    code = "architecture_snapshot_unavailable"


def require_architecture_snapshot(conn: Any, project_id: int) -> dict[str, Any]:
    """Identify the newest file-bearing snapshot, or name its recovery."""
    snapshot_id = newest_content_snapshot_id(conn, project_id)
    if snapshot_id is None:
        raise ArchitectureSnapshotUnavailable(compose_refusal(
            "architecture_snapshot_unavailable: no path snapshot carries files",
            recovery=f"Run `yoke project snapshot sync --project {project_id}` "
                     "from the project's checkout, then retry architecture health",
        ))
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"SELECT commit_sha FROM path_snapshots WHERE id = {marker}",
        (snapshot_id,),
    ).fetchone()
    return {"snapshot_id": snapshot_id, "snapshot_commit": str(row[0])}
