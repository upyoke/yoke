"""Collect portable files and restore them using destination-owned routing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain import universe_artifact_store as storage
from yoke_core.domain.qa_artifact_handle import parse_handle, serialize_handle
from yoke_core.domain.qa_artifact_owner import requirement_storage_owner
from yoke_core.domain.universe_archive import UniverseArchiveError
from yoke_core.domain.universe_archive_artifacts import MANIFEST, safe_key


def artifact_sources(conn: Any, stores: dict) -> list[dict]:
    sources = []
    rows = conn.execute(
        "SELECT a.id, a.artifact_handle, r.qa_requirement_id, a.qa_run_id "
        "FROM qa_artifacts a LEFT JOIN qa_runs r ON r.id=a.qa_run_id ORDER BY a.id"
    ).fetchall()
    for artifact_id, raw, requirement_id, run_id in rows:
        entry = {
            "artifact_id": int(artifact_id),
            "key": f"qa-artifacts/imported/{artifact_id}/artifact",
        }
        try:
            handle = parse_handle(raw)
            from yoke_core.domain.db_row import postgres_row_factory

            with conn.cursor(row_factory=postgres_row_factory) as cursor:
                owner = requirement_storage_owner(cursor, int(requirement_id))
            from yoke_core.domain.qa_artifact_handle import build_artifact_key
            from yoke_core.domain.qa_artifacts import case_artifact_subject

            filename = Path(handle.get("path") or handle["key"]).name
            entry.update(
                original_handle=handle,
                project=str(owner["project"]),
                key=build_artifact_key(
                    str(owner["project"]),
                    case_artifact_subject(owner),
                    int(run_id),
                    f"{artifact_id}-{filename}",
                ),
            )
            if handle["backend"] == "local":
                from yoke_core.domain.project_checkout_locations import (
                    checkout_for_project_id,
                )

                checkout = checkout_for_project_id(int(owner["project_id"]))
                entry["repo_root"] = str(checkout) if checkout is not None else None
        except (TypeError, ValueError, LookupError):
            entry.update(
                original_handle=raw,
                status="missing",
                reason="artifact_handle_or_owner_unavailable",
            )
        sources.append(entry)
    try:
        sources.extend(storage.shared_sources(conn, stores))
    except Exception as exc:
        raise UniverseArchiveError(
            "archive_shared_files_unlisted: cannot list the source store; "
            "repair its access or export with --exclude-artifacts"
        ) from exc
    return sources


def collect_artifacts(conn: Any, work_dir: Path) -> tuple[dict, dict[str, Path]]:
    stores = storage.project_stores(conn)
    entries, files = [], {}
    for source in artifact_sources(conn, stores):
        entry = {k: v for k, v in source.items() if k not in {"repo_root", "bytes"}}
        key = safe_key(entry["key"])
        if entry.get("status") != "missing":
            target = work_dir / key
            try:
                with storage.read_handle(
                    entry["original_handle"],
                    project=entry["project"],
                    store=stores.get(entry["project"], {}),
                    repo_root=source.get("repo_root"),
                ) as stream:
                    digest, size = storage.copy_bounded(stream, target)
                entry.update(status="included", sha256=digest, bytes=size)
                files[key] = target
            except Exception as exc:
                target.unlink(missing_ok=True)
                entry.update(
                    status="missing",
                    reason=(
                        "artifact_source_unreadable:"
                        + storage.safe_aws_error_reason(exc)
                    ),
                )
        entries.append(entry)
    return {"version": 1, "entries": entries}, files


def capture_destination(dsn: str) -> dict:
    conn = db_backend.connect_psycopg(dsn)
    try:
        return storage.project_stores(conn)
    finally:
        conn.close()


def restore_artifacts(conn: Any, dump: Path, stores: dict) -> dict:
    """Run inside the restore transaction; never commit the caller's writes."""
    manifest_path = dump.parent / MANIFEST
    if not manifest_path.is_file():
        return {"included": 0, "missing": 0, "manifest": False}
    manifest = json.loads(manifest_path.read_bytes())
    included = missing = 0
    from yoke_core.domain.db_savepoint import savepoint

    with savepoint(conn, "restored_artifact_files", owns=False):
        storage.apply_destination_settings(conn, stores)
        for entry in manifest["entries"]:
            if entry["status"] == "missing":
                missing += 1
                continue
            key = safe_key(entry["key"])
            project = entry.get("project")
            if not isinstance(project, str) or not project:
                raise UniverseArchiveError(
                    "archive_artifact_owner_missing: file has no project; export again"
                )
            original = parse_handle(entry["original_handle"])
            if key.startswith("qa-artifacts/"):
                row = conn.execute(
                    "SELECT artifact_handle FROM qa_artifacts WHERE id=%s",
                    (entry.get("artifact_id"),),
                ).fetchone()
                if row is None or parse_handle(row[0]) != original:
                    raise UniverseArchiveError(
                        "archive_artifact_handle_mismatch: manifest differs from the "
                        "dump; export the source again"
                    )
            handle = storage.write_file(
                dump.parent / "artifacts" / key,
                key,
                project=project,
                store=stores.get(project, {}),
                content_type=original.get("content_type"),
            )
            if key.startswith("qa-artifacts/"):
                conn.execute(
                    "UPDATE qa_artifacts SET artifact_handle=%s WHERE id=%s",
                    (serialize_handle(handle), entry["artifact_id"]),
                )
            included += 1
    return {"included": included, "missing": missing, "manifest": True}


def estimate_universe(
    *, dsn: str | None = None, exclude_artifacts: bool = False
) -> dict:
    """Estimate before dumping; missing files remain explicitly counted."""
    from yoke_core.domain.universe_export import (
        resolve_export_dsn,
        _start_own_universe,
        _snapshot_connection,
    )

    resolved_dsn = dsn or resolve_export_dsn()
    _start_own_universe(resolved_dsn, lambda _line: None)
    conn = _snapshot_connection(resolved_dsn)
    try:
        dump_bytes = int(
            conn.execute("SELECT pg_database_size(current_database())").fetchone()[0]
        )
        total = missing = count = 0
        if not exclude_artifacts:
            stores = storage.project_stores(conn)
            for source in artifact_sources(conn, stores):
                count += 1
                if source.get("status") == "missing":
                    missing += 1
                    continue
                try:
                    if "bytes" in source:
                        total += source["bytes"]
                    else:
                        total += storage.handle_size(
                            source["original_handle"],
                            project=source["project"],
                            store=stores.get(source["project"], {}),
                            repo_root=source.get("repo_root"),
                        )
                except Exception:
                    missing += 1
        return {
            "estimated_dump_bytes": dump_bytes,
            "artifact_bytes": total,
            "estimated_bytes": dump_bytes + total,
            "artifact_count": count,
            "missing_artifacts": missing,
            "estimate": True,
        }
    finally:
        conn.close()
