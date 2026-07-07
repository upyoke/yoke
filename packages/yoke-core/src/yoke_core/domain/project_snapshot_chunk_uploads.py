"""Server-side staging for chunked project snapshot sync."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from yoke_contracts.path_snapshot import (
    PathSnapshotPayload,
    PathSnapshotSyncPayload,
)
from yoke_contracts.path_snapshot_chunks import PathSnapshotChunkSyncPayload
from yoke_core.domain import db_backend, json_helper

SyncSnapshotPayload = Callable[[str, PathSnapshotSyncPayload], Dict[str, Any]]


def sync_chunk(
    project_ref: Optional[str],
    payload: PathSnapshotChunkSyncPayload,
    sync_payload: SyncSnapshotPayload,
) -> Dict[str, Any]:
    from yoke_core.domain import db_helpers
    from yoke_core.domain.project_identity import resolve_project_id

    with db_helpers.connect() as conn:
        _ensure_chunk_tables(conn)
        if payload.operation == "begin":
            assert project_ref is not None
            project_id = resolve_project_id(conn, project_ref)
            result = _begin_chunk_upload(conn, project_ref, project_id, payload)
            result["project_id"] = project_id
            return result
        if payload.operation == "append":
            return _append_chunk_upload(conn, payload)
        if payload.operation == "abort":
            return _delete_chunk_upload(conn, payload.upload_id, status="aborted")
        return _finalize_chunk_upload(conn, payload.upload_id, sync_payload)


def _ensure_chunk_tables(conn: Any) -> None:
    from yoke_core.domain.schema_init_path_tables import (
        create_path_snapshot_sync_upload_tables,
    )

    create_path_snapshot_sync_upload_tables(conn)


def _begin_chunk_upload(
    conn: Any,
    project_ref: str,
    project_id: int,
    payload: PathSnapshotChunkSyncPayload,
) -> Dict[str, Any]:
    from yoke_core.domain.path_snapshot_payload_materializer import (
        find_existing_snapshot_id,
    )

    if payload.snapshot is None:
        raise ValueError("begin requires snapshot metadata")
    p = _p(conn)
    _delete_chunk_upload_rows(conn, payload.upload_id)
    existing_snapshot_id = find_existing_snapshot_id(
        conn, project_id=project_id, commit_sha=payload.snapshot.commit_sha,
    )
    if existing_snapshot_id is not None:
        conn.commit()
        return {
            "status": "reused",
            "upload_id": payload.upload_id,
            "snapshot_id": existing_snapshot_id,
            "snapshots": [{
                "status": "reused",
                "snapshot_id": existing_snapshot_id,
                "ref": payload.snapshot.ref,
                "commit_sha": payload.snapshot.commit_sha,
                "entry_count": 0,
                "symlink_count": 0,
            }],
            "warnings": list(payload.snapshot.warnings),
            "expected_file_count": payload.snapshot.file_count,
            "expected_chunk_count": payload.snapshot.chunk_count,
        }
    conn.execute(
        "INSERT INTO path_snapshot_sync_uploads "
        "(upload_id, project_ref, repo_root, ref, commit_sha, "
        "expected_file_count, expected_chunk_count, warnings_json, "
        f"symlinks_json, created_at) VALUES ({p}, {p}, {p}, {p}, {p}, "
        f"{p}, {p}, {p}, {p}, {p})",
        (
            payload.upload_id,
            project_ref,
            payload.repo_root,
            payload.snapshot.ref,
            payload.snapshot.commit_sha,
            payload.snapshot.file_count,
            payload.snapshot.chunk_count,
            json_helper.dumps_compact(payload.snapshot.warnings),
            json_helper.dumps_compact([
                fact.model_dump(mode="json")
                for fact in payload.snapshot.symlinks
            ]),
            _now_iso(),
        ),
    )
    conn.commit()
    return {
        "status": "chunk_upload_started",
        "upload_id": payload.upload_id,
        "expected_file_count": payload.snapshot.file_count,
        "expected_chunk_count": payload.snapshot.chunk_count,
    }


def _append_chunk_upload(
    conn: Any,
    payload: PathSnapshotChunkSyncPayload,
) -> Dict[str, Any]:
    if payload.chunk_index is None:
        raise ValueError("append requires chunk_index")
    upload = _load_upload(conn, payload.upload_id)
    if upload is None:
        raise ValueError(f"snapshot chunk upload {payload.upload_id!r} not found")
    expected_chunk_count = int(_row_get(upload, "expected_chunk_count", 6))
    if payload.chunk_index >= expected_chunk_count:
        raise ValueError(
            f"chunk_index {payload.chunk_index} is outside expected range "
            f"0..{expected_chunk_count - 1}"
        )
    p = _p(conn)
    files_json = json_helper.dumps_compact([
        entry.model_dump(mode="json") for entry in payload.files
    ])
    conn.execute(
        "INSERT INTO path_snapshot_sync_upload_chunks "
        f"(upload_id, chunk_index, files_json) VALUES ({p}, {p}, {p}) "
        "ON CONFLICT (upload_id, chunk_index) DO UPDATE SET files_json = "
        "EXCLUDED.files_json",
        (payload.upload_id, payload.chunk_index, files_json),
    )
    conn.commit()
    return {
        "status": "chunk_uploaded",
        "upload_id": payload.upload_id,
        "chunk_index": payload.chunk_index,
        "file_count": len(payload.files),
    }


def _finalize_chunk_upload(
    conn: Any,
    upload_id: str,
    sync_payload: SyncSnapshotPayload,
) -> Dict[str, Any]:
    upload = _load_upload(conn, upload_id)
    if upload is None:
        raise ValueError(f"snapshot chunk upload {upload_id!r} not found")
    chunks = _load_chunks(conn, upload_id)
    expected_chunk_count = int(_row_get(upload, "expected_chunk_count", 6))
    if len(chunks) != expected_chunk_count:
        raise ValueError(
            f"snapshot chunk upload {upload_id!r} has {len(chunks)} of "
            f"{expected_chunk_count} chunks"
        )
    files = _load_chunk_files(upload_id, chunks, expected_chunk_count)
    expected_file_count = int(_row_get(upload, "expected_file_count", 5))
    if len(files) != expected_file_count:
        raise ValueError(
            f"snapshot chunk upload {upload_id!r} has {len(files)} files, "
            f"expected {expected_file_count}"
        )
    symlinks = json_helper.loads_text(str(_row_get(upload, "symlinks_json", 8)))
    warnings = json_helper.loads_text(str(_row_get(upload, "warnings_json", 7)))
    payload = PathSnapshotPayload(
        ref=str(_row_get(upload, "ref", 3)),
        commit_sha=str(_row_get(upload, "commit_sha", 4)),
        files=files,
        symlinks=symlinks if isinstance(symlinks, list) else [],
        warnings=warnings if isinstance(warnings, list) else [],
    )
    project_ref = str(_row_get(upload, "project_ref", 1))
    result = sync_payload(project_ref, PathSnapshotSyncPayload(
        project_id=project_ref,
        repo_root=_row_get(upload, "repo_root", 2),
        snapshots=[payload],
    ))
    _delete_chunk_upload_rows(conn, upload_id)
    conn.commit()
    return {
        **result,
        "upload_id": upload_id,
        "status": "chunk_upload_finalized",
    }


def _load_chunk_files(
    upload_id: str,
    chunks: Dict[int, str],
    expected_chunk_count: int,
) -> List[Dict[str, Any]]:
    files: List[Dict[str, Any]] = []
    for index in range(expected_chunk_count):
        if index not in chunks:
            raise ValueError(
                f"snapshot chunk upload {upload_id!r} missing chunk {index}"
            )
        raw_files = json_helper.loads_text(chunks[index])
        if not isinstance(raw_files, list):
            raise ValueError(f"snapshot chunk {index} is not a file list")
        files.extend(raw_files)
    return files


def _delete_chunk_upload(conn: Any, upload_id: str, *, status: str) -> Dict[str, Any]:
    _delete_chunk_upload_rows(conn, upload_id)
    conn.commit()
    return {"status": status, "upload_id": upload_id}


def _delete_chunk_upload_rows(conn: Any, upload_id: str) -> None:
    p = _p(conn)
    conn.execute(
        f"DELETE FROM path_snapshot_sync_upload_chunks WHERE upload_id = {p}",
        (upload_id,),
    )
    conn.execute(
        f"DELETE FROM path_snapshot_sync_uploads WHERE upload_id = {p}",
        (upload_id,),
    )


def _load_upload(conn: Any, upload_id: str) -> Optional[Any]:
    p = _p(conn)
    return conn.execute(
        "SELECT upload_id, project_ref, repo_root, ref, commit_sha, "
        "expected_file_count, expected_chunk_count, warnings_json, "
        "symlinks_json, created_at FROM path_snapshot_sync_uploads "
        f"WHERE upload_id = {p}",
        (upload_id,),
    ).fetchone()


def _load_chunks(conn: Any, upload_id: str) -> Dict[int, str]:
    p = _p(conn)
    rows = conn.execute(
        "SELECT chunk_index, files_json "
        "FROM path_snapshot_sync_upload_chunks "
        f"WHERE upload_id = {p} ORDER BY chunk_index",
        (upload_id,),
    ).fetchall()
    return {
        int(_row_get(row, "chunk_index", 0)): str(_row_get(row, "files_json", 1))
        for row in rows
    }


def _row_get(row: Any, key: str, index: int) -> Any:
    try:
        return row[key]
    except (KeyError, TypeError, IndexError):
        return row[index]


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _now_iso() -> str:
    from yoke_core.domain.db_helpers import iso8601_now

    return iso8601_now()


__all__ = ["sync_chunk"]
