"""Shared scaffolding for ``test_backlog_github_sync_*`` modules.

Filename omits the ``test_`` prefix so pytest does not collect it. Each split
file imports the patch-target constants and the ``make_db``/``completed_process``
helpers, then composes its own monkeypatch / context-manager combinations
locally. This keeps fixtures local to their consumer files (so future moves
do not pull surprise dependencies) while sharing database setup and
mock-process plumbing.
"""

from __future__ import annotations

import subprocess
from contextlib import contextmanager
from unittest.mock import patch

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
    """Clone this worker's cached production schema, then seed
    a single ``externalwebapp`` project row and canonical actors.

    Most ``test_backlog_github_sync_*`` cases exercise sync against the
    ``externalwebapp`` project, so the row is pre-inserted to keep individual tests
    focused on the sync surface they are exercising. The canonical
    yoke-core + local human actors are seeded so rows
    that store ``items.source`` / ``items.owner`` as numeric actor ids
    resolve through ``actor_name_or_passthrough``. Tests that need a
    different fixture build their own connection inline (see
    ``test_missing_projects_table_fails_open_to_default_repo``).
    """
    from runtime.api.fixtures.backlog import seed_test_canonical_human
    from runtime.api.fixtures.file_test_db import (
        _apply_production_schema,
        _schema_template_db,
    )
    from runtime.api.fixtures.pg_testdb import (
        connect_test_database,
        create_test_database,
        drop_database_on_close,
    )

    db_name = create_test_database(
        template=_schema_template_db(_apply_production_schema)
    )
    conn = connect_test_database(db_name)
    conn.execute(
        "INSERT INTO projects "
        "(id, slug, name, github_repo, public_item_prefix, github_sync_mode, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (id) DO UPDATE SET github_repo = EXCLUDED.github_repo, "
        "github_sync_mode = EXCLUDED.github_sync_mode",
        (
            2,
            "externalwebapp",
            "ExternalWebapp",
            "org/externalwebapp",
            "YOK",
            "enabled",
            "2026-01-01T00:00:00Z",
        ),
    )
    seed_test_canonical_human(conn)
    conn.commit()
    return drop_database_on_close(conn, db_name)


__all__ = [
    "GH_PATCH",
    "GH_DEDUP_PATCH",
    "completed_process",
    "issue_access",
    "issue_with",
    "make_db",
]


ITEM_DEDUP_PATCH = "yoke_core.domain.github_dedup.github_rest.list_issues"
ITEM_CREATE_PATCH = (
    "yoke_core.domain.backlog_github_item_create.github_rest.create_issue"
)


def item_auth_resolver(*args, **kwargs):
    from yoke_core.domain.project_github_auth import ProjectGithubAuth

    proj = kwargs.get("project") or (args[0] if args else "externalwebapp")
    return ProjectGithubAuth(
        project=proj,
        repo="org/externalwebapp",
        token="ghs_fake",
    )


def fake_issue(
    number: int = 999,
    title: str = "title",
    html_url: str | None = None,
):
    from yoke_core.domain import github_rest

    return github_rest.Issue(
        number=number,
        title=title,
        state="OPEN",
        html_url=(
            f"https://github.com/org/externalwebapp/issues/{number}"
            if html_url is None
            else html_url
        ),
    )


def issue_with(*labels: str, number: int = 55, state: str = "OPEN"):
    """A validated issue as the one issue read returns it."""
    from yoke_core.domain import github_rest

    return github_rest.Issue(
        number=number, title="title", state=state, labels=tuple(labels)
    )


@contextmanager
def issue_access(issue, *, auth=None):
    """Stub the one write-auth resolve and the validating issue read.

    ``issue=None`` makes the read fail validation; ``auth=None`` defaults
    to the fake ``org/externalwebapp`` auth.
    """
    with patch(
        f"{GH_PATCH}._issue_write_auth",
        return_value=auth or item_auth_resolver("externalwebapp"),
    ) as resolve, patch(
        f"{GH_PATCH}._fetch_validated_issue", return_value=issue,
    ) as fetch:
        yield resolve, fetch
