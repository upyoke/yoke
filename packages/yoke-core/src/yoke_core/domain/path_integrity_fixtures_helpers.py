"""Internal seeding helpers shared by the path-integrity fixtures.

Used only by :mod:`yoke_core.domain.path_integrity_fixtures_seed`
sibling modules. No public surface; tests reach for the public catalog
in :mod:`yoke_core.domain.path_integrity_fixtures` instead.

Fixtures bypass the canonical CPR scanner and write substrate rows
directly. The scanner is observation-only and cannot, by contract,
produce the malformed states the verifier must defend against (see
:mod:`yoke_core.domain.path_registry` C5).
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now


KIND_FILE = "file"
KIND_DIRECTORY = "directory"
ROOT = ""
FIXTURE_PROJECT_IDS = {
    "fix_clean": 101,
    "fix_dupe": 102,
    "fix_pc": 103,
    "fix_pc_other": 104,
    "fix_idem": 105,
    "fix_cont": 106,
    "fix_ctx": 107,
    "fix_drift": 108,
    "fix_drift_other": 109,
}


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def project_row_id(project_id: str | int) -> int:
    """Map fixture slugs to stable numeric project ids."""
    if isinstance(project_id, int):
        return project_id
    text = str(project_id)
    if text.isdigit():
        return int(text)
    return FIXTURE_PROJECT_IDS[text]


def record_fixture_row(
    conn: Any,
    *,
    name: str,
    description: str,
    project_id: str | int,
    expected_invariant_kind: Optional[str],
) -> int:
    p = _p(conn)
    numeric_project_id = project_row_id(project_id)
    cur = conn.execute(
        "INSERT INTO path_integrity_fixtures "
        "(name, description, seeded_at, project_id, "
        " expected_invariant_kind) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}) "
        "RETURNING id",
        (
            name,
            description,
            iso8601_now(),
            numeric_project_id,
            expected_invariant_kind,
        ),
    )
    return int(cur.fetchone()[0])


def ensure_project_row(
    conn: Any, project_id: str | int
) -> None:
    """Insert a minimal projects row if one does not exist."""
    p = _p(conn)
    numeric_project_id = project_row_id(project_id)
    slug = str(project_id) if not str(project_id).isdigit() else f"project-{project_id}"
    row = conn.execute(
        f"SELECT 1 FROM projects WHERE id={p}", (numeric_project_id,)
    ).fetchone()
    if row is not None:
        return
    conn.execute(
        "INSERT INTO projects (id, slug, name, created_at) "
        f"VALUES ({p}, {p}, {p}, {p})",
        (
            numeric_project_id,
            slug,
            slug,
            iso8601_now(),
        ),
    )


def mint_target(
    conn: Any,
    *,
    project_id: str | int,
    path_string: str,
    kind: str,
    parent_target_id: Optional[int],
    generation: int = 1,
) -> int:
    p = _p(conn)
    numeric_project_id = project_row_id(project_id)
    cur = conn.execute(
        "INSERT INTO path_targets "
        "(project_id, kind, path_string, generation, "
        " parent_target_id, created_at) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}) "
        "RETURNING id",
        (numeric_project_id, kind, path_string, generation,
         parent_target_id, iso8601_now()),
    )
    return int(cur.fetchone()[0])


def mint_snapshot(
    conn: Any,
    *,
    project_id: str | int,
    commit_sha: str,
    target_ids,
) -> int:
    p = _p(conn)
    numeric_project_id = project_row_id(project_id)
    cur = conn.execute(
        "INSERT INTO path_snapshots "
        f"(project_id, commit_sha, built_at) VALUES ({p}, {p}, {p}) "
        "RETURNING id",
        (numeric_project_id, commit_sha, iso8601_now()),
    )
    snapshot_id = int(cur.fetchone()[0])
    for tid in target_ids:
        conn.execute(
            "INSERT INTO path_snapshot_entries "
            f"(snapshot_id, target_id) VALUES ({p}, {p})",
            (snapshot_id, tid),
        )
    return snapshot_id


__all__ = [
    "KIND_DIRECTORY",
    "KIND_FILE",
    "ROOT",
    "ensure_project_row",
    "mint_snapshot",
    "mint_target",
    "project_row_id",
    "record_fixture_row",
]
