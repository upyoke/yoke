"""Materialize client-scanned path-snapshot payloads into DB rows."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from yoke_contracts.path_snapshot import (
    KIND_FILE,
    PathSnapshotPayload,
    SnapshotFileEntry,
    all_paths_with_kinds,
)
from yoke_core.domain import db_backend
from yoke_core.domain.path_snapshot_context_cache import (
    build_snapshot_context_cache,
)
from yoke_core.domain.path_snapshot_enrichment import _DEFAULT_DIRECTORY_TUPLE
from yoke_core.domain.path_snapshot_targets import resolve_snapshot_target_ids
from yoke_core.domain.path_targets_materialization import materialize_planned_target
from yoke_core.domain.project_identity import resolve_project_id


@dataclass(frozen=True)
class PayloadMaterializeResult:
    status: str
    snapshot_id: int
    ref: str
    commit_sha: str
    entry_count: int
    symlink_count: int


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def find_existing_snapshot_id(
    conn: Any, project_id: int, commit_sha: str
) -> Optional[int]:
    """Return the existing snapshot id for a project commit, when present."""
    p = _p(conn)
    row = conn.execute(
        "SELECT id FROM path_snapshots "
        f"WHERE project_id = {p} AND commit_sha = {p}",
        (project_id, commit_sha),
    ).fetchone()
    if row is None:
        return None
    return int(row[0])


def materialize_snapshot_payload(
    conn: Any,
    *,
    project_id: int | str,
    payload: PathSnapshotPayload,
) -> PayloadMaterializeResult:
    resolved_project_id = resolve_project_id(conn, project_id)
    existing = find_existing_snapshot_id(
        conn, resolved_project_id, payload.commit_sha,
    )
    if existing is not None:
        return PayloadMaterializeResult(
            status="reused",
            snapshot_id=existing,
            ref=payload.ref,
            commit_sha=payload.commit_sha,
            entry_count=0,
            symlink_count=0,
        )

    targets = all_paths_with_kinds(entry.path for entry in payload.files)
    files = {entry.path: entry for entry in payload.files}
    now_iso = _utc_now_iso()
    p = _p(conn)
    try:
        conn.execute("BEGIN")
        existing = find_existing_snapshot_id(
            conn, resolved_project_id, payload.commit_sha,
        )
        if existing is not None:
            conn.execute("ROLLBACK")
            return PayloadMaterializeResult(
                status="reused",
                snapshot_id=existing,
                ref=payload.ref,
                commit_sha=payload.commit_sha,
                entry_count=0,
                symlink_count=0,
            )
        resolution = resolve_snapshot_target_ids(
            conn, project_id=resolved_project_id,
            targets=targets, now_iso=now_iso,
        )
        cur = conn.execute(
            "INSERT INTO path_snapshots "
            f"(project_id, commit_sha, built_at) VALUES ({p}, {p}, {p}) "
            "RETURNING id",
            (resolved_project_id, payload.commit_sha, now_iso),
        )
        snapshot_id = int(cur.fetchone()[0])
        _write_entries(
            conn, snapshot_id=snapshot_id, targets=targets,
            target_ids=resolution.target_ids, files=files,
        )
        _write_symlink_facts(
            conn, snapshot_id=snapshot_id, target_ids=resolution.target_ids,
            payload=payload,
        )
        for target_id in resolution.materialize_target_ids:
            materialize_planned_target(
                conn, target_id=target_id, commit_sha=payload.commit_sha,
            )
        conn.commit()
        return PayloadMaterializeResult(
            status="created",
            snapshot_id=snapshot_id,
            ref=payload.ref,
            commit_sha=payload.commit_sha,
            entry_count=len(targets),
            symlink_count=len(payload.symlinks),
        )
    except Exception:
        conn.rollback()
        raise


def _write_entries(
    conn: Any,
    *,
    snapshot_id: int,
    targets: List[Tuple[str, str]],
    target_ids: Dict[str, int],
    files: Dict[str, SnapshotFileEntry],
) -> None:
    context_cache = build_snapshot_context_cache(
        conn, targets=targets, target_ids=target_ids,
    )
    rows: List[Tuple] = []
    for path_string, kind in targets:
        target_id = target_ids[path_string]
        if kind == KIND_FILE:
            entry = files[path_string]
            rows.append((
                snapshot_id,
                target_id,
                entry.line_count,
                entry.language,
                entry.module_name,
                context_cache.area_for(target_id),
                context_cache.is_generated(target_id),
                json.dumps(entry.dependency_edges, sort_keys=True),
            ))
        else:
            rows.append((snapshot_id, target_id) + _DEFAULT_DIRECTORY_TUPLE)
    p = _p(conn)
    _executemany(
        conn,
        "INSERT INTO path_snapshot_entries (snapshot_id, target_id, "
        "line_count, language, module_name, area, is_generated, "
        f"dependency_edges) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})",
        rows,
    )


def _write_symlink_facts(
    conn: Any,
    *,
    snapshot_id: int,
    target_ids: Dict[str, int],
    payload: PathSnapshotPayload,
) -> None:
    if not payload.symlinks:
        return
    _ensure_symlink_fact_table(conn)
    rows = []
    for fact in payload.symlinks:
        rows.append((
            snapshot_id,
            fact.path,
            target_ids.get(fact.path),
            fact.reason,
            fact.target_attempt,
            fact.canonical_path,
            target_ids.get(fact.canonical_path or ""),
        ))
    p = _p(conn)
    _executemany(
        conn,
        "INSERT INTO path_snapshot_symlink_facts ("
        "snapshot_id, symlink_path, symlink_target_id, reason, "
        "target_attempt, canonical_path, canonical_target_id"
        f") VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p})",
        rows,
    )


def _ensure_symlink_fact_table(conn: Any) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS path_snapshot_symlink_facts (
            snapshot_id INTEGER NOT NULL,
            symlink_path TEXT NOT NULL,
            symlink_target_id INTEGER,
            reason TEXT NOT NULL,
            target_attempt TEXT,
            canonical_path TEXT,
            canonical_target_id INTEGER,
            PRIMARY KEY (snapshot_id, symlink_path),
            FOREIGN KEY (snapshot_id) REFERENCES path_snapshots(id),
            FOREIGN KEY (symlink_target_id) REFERENCES path_targets(id),
            FOREIGN KEY (canonical_target_id) REFERENCES path_targets(id)
        )
    """)


def _executemany(conn: Any, sql: str, rows: List[Tuple]) -> None:
    if db_backend.connection_is_postgres(conn):
        with getattr(conn, "_inner", conn).cursor() as cur:
            cur.executemany(sql, rows)
        return
    conn.executemany(sql, rows)


__all__ = [
    "PayloadMaterializeResult",
    "find_existing_snapshot_id",
    "materialize_snapshot_payload",
]
