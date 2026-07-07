"""path-registry HEAD-snapshot scanner.

Materializes observed git tree state into ``path_targets``,
``path_snapshots``, and ``path_snapshot_entries``. The scanner is
observation-only: no Project Structure reads and no rename inference.
Snapshot creation is transactional and idempotent for
``(project_id, commit_sha)``.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.path_registry import (
    KIND_DIRECTORY,
    KIND_FILE,
    ROOT_PATH_SENTINEL,
    _all_paths_with_kinds,
)
from yoke_core.domain.path_snapshot_enrichment import write_entries
from yoke_core.domain.path_snapshot_targets import resolve_snapshot_target_ids
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.project_checkout_locations import checkout_for_project_id
from yoke_core.domain.path_targets_materialization import materialize_planned_target


class PathSnapshotError(RuntimeError):
    """Raised when the scanner cannot produce a complete snapshot."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _resolve_repo_path(conn: Any, project_id: int) -> Path:
    checkout = checkout_for_project_id(project_id)
    if checkout is None:
        raise PathSnapshotError(
            f"project '{project_id}' has no machine-local checkout mapping; "
            "cannot scan"
        )
    if not checkout.is_dir():
        raise PathSnapshotError(
            f"project '{project_id}' checkout '{checkout}' is not a "
            "readable directory"
        )
    return checkout


def _git(repo_path: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo_path), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise PathSnapshotError(
            f"git {' '.join(args)} failed in {repo_path}: "
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )
    return proc.stdout


def _resolve_head_sha(repo_path: Path) -> str:
    sha = _git(repo_path, "rev-parse", "HEAD").strip()
    if not sha:
        raise PathSnapshotError(
            f"git rev-parse HEAD returned empty SHA in {repo_path}"
        )
    return sha


def _walk_files_at(repo_path: Path, ref: str) -> List[str]:
    """Return every committed file path at ``ref``, project-relative POSIX.

    Uses ``git ls-tree -r --name-only <ref>`` — a pure observation of
    git tree state.  No rename / similarity detection (C5).
    """
    raw = _git(repo_path, "ls-tree", "-r", "--name-only", ref)
    return [
        line for line in raw.splitlines() if line and not line.startswith(":")
    ]


def _walk_head_files(repo_path: Path) -> List[str]:
    return _walk_files_at(repo_path, "HEAD")


def _existing_snapshot_id(
    conn: Any, project_id: int, commit_sha: str
) -> Optional[int]:
    p = _p(conn)
    row = conn.execute(
        "SELECT id FROM path_snapshots "
        f"WHERE project_id = {p} AND commit_sha = {p}",
        (project_id, commit_sha),
    ).fetchone()
    if row is None:
        return None
    return int(row[0])


def _materialize_snapshot(
    conn: Any,
    project_id: int,
    commit_sha: str,
    files: List[str],
    repo_path: Path,
) -> int:
    """Inner snapshot builder shared by HEAD and arbitrary-SHA paths.

    Caller must have already verified that no row exists for
    ``(project_id, commit_sha)`` and that the file list reflects that
    commit's tree. Wraps the mint+entries+materialize work in a single
    transaction; rolls back on any failure.
    """
    targets = _all_paths_with_kinds(files)
    now_iso = _utc_now_iso()
    p = _p(conn)

    try:
        conn.execute("BEGIN")
        # Re-check inside the transaction in case a concurrent scan
        # raced ahead of us.
        existing = _existing_snapshot_id(conn, project_id, commit_sha)
        if existing is not None:
            conn.execute("ROLLBACK")
            return existing

        resolution = resolve_snapshot_target_ids(
            conn, project_id=project_id, targets=targets, now_iso=now_iso,
        )

        cur = conn.execute(
            "INSERT INTO path_snapshots "
            f"(project_id, commit_sha, built_at) VALUES ({p}, {p}, {p}) RETURNING id",
            (project_id, commit_sha, now_iso),
        )
        snapshot_id = int(cur.fetchone()[0])
        write_entries(
            conn, snapshot_id=snapshot_id, repo_path=repo_path,
            commit_sha=commit_sha, targets=targets,
            target_ids=resolution.target_ids,
        )
        for tid in resolution.materialize_target_ids:
            materialize_planned_target(
                conn, target_id=tid, commit_sha=commit_sha,
            )
        conn.commit()
        return snapshot_id
    except Exception:
        conn.rollback()
        raise


def build_head_snapshot(conn: Any, project_id: int | str) -> int:
    """Mint identity rows and a complete HEAD snapshot for ``project_id``.

    Returns the ``path_snapshots.id`` of the snapshot for HEAD.
    Idempotent: rerunning against the same HEAD commit returns the
    existing snapshot id without further mutation.
    """
    project_id = resolve_project_id(conn, project_id)
    repo_path = _resolve_repo_path(conn, project_id)
    commit_sha = _resolve_head_sha(repo_path)

    existing = _existing_snapshot_id(conn, project_id, commit_sha)
    if existing is not None:
        return existing

    files = _walk_head_files(repo_path)
    return _materialize_snapshot(conn, project_id, commit_sha, files, repo_path)


def build_snapshot_at_sha(
    conn: Any, project_id: int | str, commit_sha: str
) -> int:
    """Build a snapshot for ``project_id`` at ``commit_sha`` (any commit).

    Walks ``git ls-tree -r --name-only <commit_sha>`` rather than HEAD,
    enabling activate / boundary callers to anchor on integration-target
    SHAs that have already moved past HEAD on the working branch.

    Idempotent against ``(project_id, commit_sha)``: returns the existing
    snapshot id without mutation when one already exists. Prefer
    :func:`ensure_snapshot_at` for the lazy lookup-then-build pattern;
    callers reach for this directly only when they want to force a build
    regardless of cache state.
    """
    project_id = resolve_project_id(conn, project_id)
    repo_path = _resolve_repo_path(conn, project_id)
    if not commit_sha:
        raise PathSnapshotError(
            f"commit_sha is required for build_snapshot_at_sha "
            f"(project '{project_id}')"
        )

    existing = _existing_snapshot_id(conn, project_id, commit_sha)
    if existing is not None:
        return existing

    files = _walk_files_at(repo_path, commit_sha)
    return _materialize_snapshot(conn, project_id, commit_sha, files, repo_path)


def ensure_snapshot_at(
    conn: Any, project_id: int | str, commit_sha: str
) -> int:
    """Return the snapshot id for ``(project_id, commit_sha)``, building it
    if absent.

    Lazy: callers that only need *a* snapshot at a SHA — activate flows,
    boundary checks, post-commit hooks — go through this helper rather
    than querying ``path_snapshots`` directly. Inline build avoids the
    cold-start surprise where a freshly-cloned tree refuses operations
    until ``path_snapshots <project>`` is run by hand.
    """
    project_id = resolve_project_id(conn, project_id)
    existing = _existing_snapshot_id(conn, project_id, commit_sha)
    if existing is not None:
        return existing
    return build_snapshot_at_sha(conn, project_id, commit_sha)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.domain.path_snapshots",
        description=(
            "Build the canonical HEAD path snapshot for a project. "
            "Idempotent: rerun against the same HEAD is a no-op."
        ),
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "project_id",
        nargs="?",
        help="project id from the projects table (e.g. 'yoke')",
    )
    group.add_argument(
        "--ensure-head",
        metavar="PROJECT_ID",
        dest="ensure_head_project",
        help=(
            "ensure snapshots exist for the project's current HEAD and "
            "for the integration-target tip (origin-then-local — the same "
            "rule activation queries). Equivalent to a positional project id."
        ),
    )
    args = parser.parse_args(argv)

    project_id = args.ensure_head_project or args.project_id
    if not project_id:
        parser.error(
            "either a positional project_id or --ensure-head <project_id> "
            "is required"
        )

    from yoke_core.domain.path_claims_integration_resolver import (
        IntegrationTargetDiverged,
    )
    from yoke_core.domain.path_snapshots_integration_warm import (
        ensure_integration_target_snapshot,
    )
    from yoke_core.domain.schema_common import _connect_raw, _resolve_db_path

    conn = _connect_raw(_resolve_db_path())
    try:
        snapshot_id = build_head_snapshot(conn, project_id)
        ensure_integration_target_snapshot(conn, project_id)
    except (PathSnapshotError, IntegrationTargetDiverged) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    print(snapshot_id)
    return 0


__all__ = [
    "KIND_DIRECTORY",
    "KIND_FILE",
    "PathSnapshotError",
    "ROOT_PATH_SENTINEL",
    "build_head_snapshot",
    "build_snapshot_at_sha",
    "ensure_snapshot_at",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
