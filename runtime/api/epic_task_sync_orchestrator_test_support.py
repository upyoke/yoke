"""Shared database and REST fixtures for epic-task sync orchestration."""

from pathlib import Path
from unittest.mock import patch

import pytest

from yoke_core.domain import github_rest
from yoke_core.domain.project_github_auth import ProjectGithubAuth
from runtime.api.fixtures.file_test_db import (
    apply_fixture_schema_ddl,
    connect_test_db,
    init_test_db,
)


@pytest.fixture
def db(tmp_path):
    with init_test_db(tmp_path, apply_schema=apply_fixture_schema_ddl) as db_path:
        conn = connect_test_db(db_path)
        conn.execute(
            """
            INSERT INTO projects
                (id, slug, name, github_repo, public_item_prefix, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                slug = EXCLUDED.slug,
                name = EXCLUDED.name,
                github_repo = EXCLUDED.github_repo,
                public_item_prefix = EXCLUDED.public_item_prefix
            """,
            (
                2,
                "externalwebapp",
                "ExternalWebapp",
                "org/externalwebapp",
                "YOK",
                "2026-01-01T00:00:00Z",
            ),
        )
        conn.commit()
        try:
            yield conn
        finally:
            conn.close()


@pytest.fixture(autouse=True)
def _mock_yoke_root():
    """Prevent subprocess.run leaking into worktree git resolution."""
    with patch(
        "yoke_core.domain.epic_task_sync._yoke_root",
        return_value=Path("/tmp/fake-yoke"),
    ):
        yield


def _ok_auth(project: str, **kwargs):
    return ProjectGithubAuth(
        project=project,
        repo="org/externalwebapp",
        token="ghs_test_token",
    )


@pytest.fixture(autouse=True)
def _stub_project_github_auth():
    """Default-stub the canonical resolver to succeed across the
    orchestrator + create helper + label-ensure paths."""
    with (
        patch(
            "yoke_core.domain.epic_task_sync_github_orchestrator."
            "resolve_project_github_auth",
            side_effect=_ok_auth,
        ),
        patch(
            "yoke_core.domain.epic_task_sync_github.resolve_project_github_auth",
            side_effect=_ok_auth,
        ),
        patch(
            "yoke_core.domain.epic_task_sync_github_create.resolve_project_github_auth",
            side_effect=_ok_auth,
        ),
    ):
        yield


@pytest.fixture(autouse=True)
def _stub_typed_rest_surfaces():
    """Stub the typed REST surfaces the orchestrator + create helpers
    drive: label ensure, issue create, sub-issue link (which fails so
    the orchestrator falls back to the body-checkbox path), dedup
    search (always empty so a new issue is created)."""
    create_counter = [0]

    def fake_create_issue(*, project, title, body, labels, **_):
        create_counter[0] += 1
        if "workflow:epic" in labels:
            number = 100
        else:
            number = 100 + create_counter[0]
        return github_rest.Issue(
            number=number,
            title=title,
            state="OPEN",
            html_url=f"https://github.com/org/externalwebapp/issues/{number}",
        )

    with (
        patch(
            "yoke_core.domain.epic_task_sync_github_create.github_rest.create_issue",
            side_effect=fake_create_issue,
        ),
        patch(
            "yoke_core.domain.epic_task_sync_github._label_rest.ensure_label",
        ),
        patch(
            "yoke_core.domain.github_rest.add_sub_issue",
            side_effect=github_rest.RestTransportError(
                "sub-issue not supported", status=404
            ),
        ),
        patch(
            "yoke_core.domain.github_dedup.github_rest.list_issues",
            return_value=[],
        ),
        patch(
            "yoke_core.domain.epic_task_sync_github_orchestrator_body."
            "append_task_list_to_epic_body",
        ),
    ):
        yield
