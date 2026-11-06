# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from pathlib import Path

from unittest.mock import patch

import pytest

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ISSUES_WRITE_PERMISSION_LEVELS,
)

from runtime.api.conftest import insert_epic_task, insert_item

from yoke_core.domain import epic_task_sync

from yoke_core.domain.project_github_auth import (
    ProjectGithubAuth,
)

from runtime.api.fixtures.file_test_db import (
    apply_test_schema,
    connect_test_db,
    init_test_db,
)


@pytest.fixture
def db(tmp_path):
    with init_test_db(tmp_path, apply_schema=apply_test_schema) as db_path:
        conn = connect_test_db(db_path)
        conn.execute(
            """
            INSERT INTO projects
                (id, slug, name, github_repo, public_item_prefix, github_sync_mode, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                slug = EXCLUDED.slug,
                name = EXCLUDED.name,
                github_repo = EXCLUDED.github_repo,
                public_item_prefix = EXCLUDED.public_item_prefix,
                github_sync_mode = EXCLUDED.github_sync_mode
            """,
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
        conn.commit()
        try:
            yield conn
        finally:
            conn.close()


def _seed_progress_note(
    db, *, epic_id: int, task_num: int, note_num: int, body: str
) -> None:
    db.execute(
        """
        INSERT INTO epic_progress_notes
            (epic_id, task_num, note_num, body, synced_to_github, created_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (epic_id, task_num, note_num, body, 0, "2026-01-01T00:00:00Z"),
    )
    db.commit()


@pytest.fixture(autouse=True)
def _stub_project_github_auth():
    """Keep project-scoped GitHub calls on the test resolver."""

    def _ok(project, **kwargs):
        return ProjectGithubAuth(
            project=project,
            repo="org/externalwebapp",
            token="ghs_test",
        )

    with patch(
        "yoke_core.domain.epic_task_sync_github.resolve_project_github_auth",
        side_effect=_ok,
    ) as resolver:
        yield resolver
