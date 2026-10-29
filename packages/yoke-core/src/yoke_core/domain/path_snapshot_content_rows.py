"""Which stored path snapshots carry file contents.

A snapshot answers path questions only when its entries hold the commit's
files. A row holding just the root directory carries no contents: it names
a commit without saying what that commit contains. Every snapshot reader
that would reuse a row for its commit goes through here, so a content-less
row is never mistaken for the commit's inventory, and a content build for
that commit discards it first. Path resolution likewise reads disappearance
only from snapshots that carry contents.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_contracts.path_snapshot import KIND_FILE
from yoke_core.domain import db_backend


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def find_content_snapshot_id(
    conn: Any, project_id: int, commit_sha: str
) -> Optional[int]:
    """Return the project's snapshot id for ``commit_sha`` if it has files."""
    p = _p(conn)
    row = conn.execute(
        "SELECT s.id FROM path_snapshots s "
        f"WHERE s.project_id = {p} AND s.commit_sha = {p} AND EXISTS ("
        "  SELECT 1 FROM path_snapshot_entries e "
        "  JOIN path_targets t ON t.id = e.target_id "
        f"  WHERE e.snapshot_id = s.id AND t.kind = {p})",
        (project_id, commit_sha, KIND_FILE),
    ).fetchone()
    if row is None:
        return None
    return int(row[0])


def newest_content_snapshot_id(conn: Any, project_id: int) -> Optional[int]:
    """Return the project's newest snapshot id that carries file contents."""
    p = _p(conn)
    row = conn.execute(
        "SELECT MAX(s.id) FROM path_snapshots s "
        f"WHERE s.project_id = {p} AND EXISTS ("
        "  SELECT 1 FROM path_snapshot_entries e "
        "  JOIN path_targets t ON t.id = e.target_id "
        f"  WHERE e.snapshot_id = s.id AND t.kind = {p})",
        (project_id, KIND_FILE),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return int(row[0])


def discard_contentless_snapshot(conn: Any, project_id: int, commit_sha: str) -> None:
    """Delete the commit's snapshot row, which the caller proved content-less.

    Runs inside the caller's write transaction, after
    :func:`find_content_snapshot_id` returned ``None`` there.
    """
    p = _p(conn)
    snapshot = (
        f"SELECT id FROM path_snapshots WHERE project_id = {p} AND commit_sha = {p}"
    )
    for table in ("path_snapshot_symlink_facts", "path_snapshot_entries"):
        conn.execute(
            f"DELETE FROM {table} WHERE snapshot_id IN ({snapshot})",
            (project_id, commit_sha),
        )
    conn.execute(
        f"DELETE FROM path_snapshots WHERE project_id = {p} AND commit_sha = {p}",
        (project_id, commit_sha),
    )


class ContentlessSnapshotConflict(RuntimeError):
    """A concurrent writer committed a snapshot row for the commit with no files."""


def insert_snapshot_row(
    conn: Any, project_id: int, commit_sha: str, built_at: Any
) -> tuple[int, bool]:
    """Insert the commit's snapshot row inside the caller's write transaction.

    Returns ``(snapshot_id, True)`` for a new row. When a concurrent sync of
    the same commit committed its row first, returns ``(that_id, False)``;
    the commit's files are fixed, so the caller rolls back and reuses it.
    """
    p = _p(conn)
    row = conn.execute(
        "INSERT INTO path_snapshots (project_id, commit_sha, built_at) "
        f"VALUES ({p}, {p}, {p}) "
        "ON CONFLICT (project_id, commit_sha) DO NOTHING RETURNING id",
        (project_id, commit_sha, built_at),
    ).fetchone()
    if row is not None:
        return int(row[0]), True
    existing = find_content_snapshot_id(conn, project_id, commit_sha)
    if existing is None:
        raise ContentlessSnapshotConflict(
            f"path snapshot for project {project_id} commit {commit_sha} was "
            "committed by a concurrent writer without files; rerun "
            f"`yoke project snapshot sync --project {project_id}` to rebuild it"
        )
    return existing, False


__all__ = [
    "ContentlessSnapshotConflict",
    "discard_contentless_snapshot",
    "find_content_snapshot_id",
    "insert_snapshot_row",
    "newest_content_snapshot_id",
]
