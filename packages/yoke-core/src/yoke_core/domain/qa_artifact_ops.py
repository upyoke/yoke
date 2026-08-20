"""QA artifact CRUD operations over typed artifact handles.

Owns ``cmd_artifact_add``, ``cmd_artifact_list``, and
``linked_artifact_handle`` (file copy into the canonical scratch-backed
QA capture tree for the one-step run-add fallback). The parent
``qa_execution`` re-exports these symbols.

Every row carries an ``artifact_handle``
(:mod:`yoke_core.domain.qa_artifact_handle`); bare path payloads are
refused with the handle vocabulary in the error.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import List, Optional

from yoke_contracts.machine_qa_execution import AGENT_MISSION_ARTIFACT_LIMIT
from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import (
    connect,
    iso8601_now,
    query_one,
    query_rows,
)
from yoke_core.domain.qa_artifact_handle import (
    ArtifactHandleError,
    handle_address,
    local_handle,
    parse_handle,
    serialize_handle,
)
from yoke_core.domain.qa_constants import _pipe_row


_ART_SELECT = (
    "id, qa_run_id, artifact_type, COALESCE(content_type,''), "
    "COALESCE(artifact_handle,''), COALESCE(metadata,''), created_at"
)

BARE_PATH_GUIDANCE = (
    "qa_artifacts records typed handles, not bare paths: pass an "
    "artifact_handle JSON object — "
    '{"backend":"s3","bucket":B,"key":K} for uploaded evidence or '
    '{"backend":"local","path":P} for explicit machine-local evidence.'
)


class QaArtifactLimitError(ValueError):
    """A mission run already carries its maximum deliberate proof set."""


def ensure_artifact_capacity(conn, run_id: int | None) -> int | None:
    """Lock a run, enforce the mission cap, and return its requirement id."""
    if run_id is None:
        return None
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    lock = " FOR UPDATE OF r" if db_backend.connection_is_postgres(conn) else ""
    row = query_one(
        conn,
        "SELECT r.qa_requirement_id,q.runner_id FROM qa_runs r "
        "JOIN qa_requirements q ON q.id=r.qa_requirement_id "
        f"WHERE r.id={p}{lock}",
        (int(run_id),),
    )
    if row is None:
        return None
    if str(row["runner_id"] or "") == "agent_mission":
        count = query_one(
            conn,
            f"SELECT COUNT(*) AS artifact_count FROM qa_artifacts WHERE qa_run_id={p}",
            (int(run_id),),
        )
        artifact_count = int(count["artifact_count"] if count is not None else 0)
        if artifact_count >= AGENT_MISSION_ARTIFACT_LIMIT:
            attempted = artifact_count + 1
            raise QaArtifactLimitError(
                "exploratory mission artifact limit reached for run "
                f"{run_id}: attachment {attempted} was not added; limit is "
                f"{AGENT_MISSION_ARTIFACT_LIMIT}. Keep only deliberate proof "
                "of findings."
            )
    return int(row["qa_requirement_id"])


def linked_artifact_handle(
    conn,
    *,
    requirement_id: int,
    run_id: int,
    artifact_path: str,
) -> str:
    """Return the serialized handle for a one-step run-add artifact.

    When ``artifact_path`` points to a real file and the requirement
    targets an item row with a known project, copy the file into the
    canonical scratch-backed capture tree and return an explicit ``local``
    handle on the copied absolute path (a stable location instead of
    wherever the caller captured). Otherwise return a ``local`` handle on
    the caller-provided path. The one-step fallback is deliberately
    local-only — durable S3 upload is the orchestrator's
    presign-at-record flow.
    """
    source_path = Path(artifact_path)
    if not source_path.is_file():
        return serialize_handle(local_handle(artifact_path))

    try:
        req_row = query_one(
            conn,
            "SELECT item_id,deployment_run_id FROM qa_requirements WHERE id = %s",
            (requirement_id,),
        )
        if req_row is None:
            return serialize_handle(local_handle(str(source_path)))
        if req_row["item_id"] is not None:
            project_row = query_one(
                conn,
                "SELECT p.slug AS project FROM items i "
                "JOIN projects p ON p.id=i.project_id WHERE i.id=%s",
                (int(req_row["item_id"]),),
            )
        elif req_row["deployment_run_id"] is not None:
            project_row = query_one(
                conn,
                "SELECT p.slug AS project FROM deployment_runs dr "
                "JOIN projects p ON p.id=dr.project_id WHERE dr.id=%s",
                (str(req_row["deployment_run_id"]),),
            )
        else:
            project_row = None
        if project_row is None or not project_row["project"]:
            return serialize_handle(local_handle(str(source_path)))

        from yoke_core.domain.qa_artifacts import (
            artifact_file_path,
            case_artifact_subject,
        )

        target_path = artifact_file_path(
            str(project_row["project"]),
            case_artifact_subject(dict(req_row)),
            run_id,
            source_path.name,
        )
        if source_path.resolve() != target_path.resolve():
            shutil.copy2(source_path, target_path)
        return serialize_handle(local_handle(str(target_path)))
    except Exception:
        # Best-effort canonicalization. On Postgres a failed read (e.g. the
        # items table is absent in a minimal qa test DB) aborts the shared
        # transaction; roll back so the caller's artifact INSERT is not blocked
        # by InFailedSqlTransaction. The caller committed its run row first.
        try:
            conn.rollback()
        except Exception:
            pass
        return serialize_handle(local_handle(str(source_path)))


def cmd_artifact_add(
    *,
    db_path: Optional[str] = None,
    run_id: Optional[int] = None,
    artifact_type: str,
    content_type: Optional[str] = None,
    artifact_handle: Optional[str] = None,
    metadata: Optional[str] = None,
) -> int:
    """Insert a qa_artifact row. Returns the new ID."""
    if not artifact_type:
        print("Error: --artifact-type is required", file=sys.stderr)
        sys.exit(2)
    handle_text: Optional[str] = None
    if artifact_handle is not None:
        try:
            handle_text = serialize_handle(parse_handle(artifact_handle))
        except ArtifactHandleError as exc:
            print(f"Error: {exc}. {BARE_PATH_GUIDANCE}", file=sys.stderr)
            sys.exit(2)

    conn = connect(path=db_path)
    try:
        try:
            ensure_artifact_capacity(conn, run_id)
        except QaArtifactLimitError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(2)
        cur = conn.execute(
            """INSERT INTO qa_artifacts (qa_run_id, artifact_type, content_type, artifact_handle, metadata, created_at)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
            (run_id, artifact_type, content_type, handle_text, metadata, iso8601_now()),
        )
        inserted_id = int(cur.fetchone()[0])
        conn.commit()
    finally:
        conn.close()

    print(inserted_id)
    return inserted_id


def cmd_artifact_list(
    *,
    db_path: Optional[str] = None,
    run_id: Optional[int] = None,
    item_id: Optional[int] = None,
    resolve_addresses: bool = False,
) -> List[str]:
    """List artifacts (pipe-delimited). Returns list of formatted lines.

    ``--item-id`` joins through qa_runs → qa_requirements to find all
    artifacts for an item without requiring the caller to know run IDs.
    ``resolve_addresses`` swaps the handle column for each handle's honest
    address: a filesystem path for ``local`` handles, an ``s3://bucket/key``
    object URI for ``s3`` handles (durable objects have no machine-local
    filesystem path).
    """
    conn = connect(path=db_path)
    try:
        if item_id is not None:
            # Join through qa_runs → qa_requirements to find all artifacts for an item
            rows = query_rows(
                conn,
                "SELECT a.id, a.qa_run_id, a.artifact_type, COALESCE(a.content_type,''), "
                "COALESCE(a.artifact_handle,''), COALESCE(a.metadata,''), a.created_at "
                "FROM qa_artifacts a "
                "JOIN qa_runs r ON a.qa_run_id = r.id "
                "JOIN qa_requirements q ON r.qa_requirement_id = q.id "
                "WHERE q.item_id = %s "
                "ORDER BY a.id",
                (item_id,),
            )
        else:
            where = "1=1"
            params: tuple = ()
            if run_id is not None:
                where = "qa_run_id = %s"
                params = (run_id,)
            rows = query_rows(
                conn,
                f"SELECT {_ART_SELECT} FROM qa_artifacts WHERE {where} ORDER BY id",
                params,
            )
    finally:
        conn.close()

    lines = []
    # artifact_handle is column index 4 in _ART_SELECT
    _HANDLE_IDX = 4
    for row in rows:
        if resolve_addresses:
            row_list = list(row)
            raw = row_list[_HANDLE_IDX] if _HANDLE_IDX < len(row_list) else ""
            if raw:
                try:
                    row_list[_HANDLE_IDX] = handle_address(parse_handle(raw))
                except ArtifactHandleError:
                    row_list[_HANDLE_IDX] = f"<malformed handle: {raw}>"
            line = _pipe_row(row_list)
        else:
            line = _pipe_row(row)
        print(line)
        lines.append(line)
    if not lines and item_id is not None:
        print(f"No artifacts found for item {item_id}")
    return lines


__all__ = [
    "BARE_PATH_GUIDANCE",
    "QaArtifactLimitError",
    "cmd_artifact_add",
    "cmd_artifact_list",
    "ensure_artifact_capacity",
    "linked_artifact_handle",
]
