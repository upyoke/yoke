"""Shared scaffolding for ``test_backlog_github_sync_*`` modules.

Filename omits the ``test_`` prefix so pytest does not collect it. Each split
file imports the patch-target constants and the ``make_db``/``completed_process``
helpers, then composes its own monkeypatch / context-manager combinations
locally. This keeps fixtures local to their consumer files (so future moves
do not pull surprise dependencies) while sharing the verbose schema DDL and
mock-process plumbing.
"""

from __future__ import annotations

import subprocess

from runtime.api.fixtures.schema_ddl import apply_fixture_schema


# Patch targets used across every split file. ``backlog_github_sync`` is
# the stable module that re-exports every public sync function from
# canonical sibling modules. Each sibling looks up callable references
# through that module at call time so a patch on the stable surface
# reaches every sync operation.
GH_PATCH = "yoke_core.domain.backlog_github_sync"
GH_DEDUP_PATCH = "yoke_core.domain.github_dedup"


def completed_process(
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> "subprocess.CompletedProcess[str]":
    """Build a ``subprocess.CompletedProcess`` stand-in retained for
    callers that still mock subprocess-shaped helpers in unrelated
    modules. The backlog sync family itself now mocks typed REST
    surfaces directly."""
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def make_db():
    """Postgres disposable DB seeded with the full Yoke schema +
    a single ``externalwebapp`` project row + the canonical actor seeding.

    Most ``test_backlog_github_sync_*`` cases exercise sync against the
    ``externalwebapp`` project, so the row is pre-inserted to keep individual tests
    focused on the sync surface they are exercising. The canonical
    yoke-core + local human actors are seeded so rows
    that store ``items.source`` / ``items.owner`` as numeric actor ids
    resolve through ``actor_label_or_passthrough``. Tests that need a
    different fixture build their own connection inline (see
    ``test_missing_projects_table_fails_open_to_default_repo``).
    """
    from runtime.api.fixtures.backlog import seed_test_canonical_actors
    from runtime.api.fixtures.pg_testdb import (
        connect_test_database,
        create_test_database,
        drop_database_on_close,
    )

    db_name = create_test_database()
    conn = connect_test_database(db_name)
    apply_fixture_schema(conn)
    conn.execute(
        "INSERT INTO projects "
        "(id, slug, name, github_repo, public_item_prefix, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (id) DO UPDATE SET github_repo = EXCLUDED.github_repo",
        (2, "externalwebapp", "ExternalWebapp", "org/externalwebapp", "YOK", "2026-01-01T00:00:00Z"),
    )
    seed_test_canonical_actors(conn)
    conn.commit()
    return drop_database_on_close(conn, db_name)


__all__ = [
    "GH_PATCH",
    "GH_DEDUP_PATCH",
    "completed_process",
    "make_db",
]
