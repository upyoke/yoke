"""Doctor GitHub HC: SKIP-with-canonical-reason and PASS/FAIL on REST.

Verifies the four GitHub-dependent HCs (`orphaned-gh-issues`,
`gh-orphan-detection`, `wrong-repo-issues`, `project-gh-secrets`):

- SKIP with :data:`yoke_core.engines.doctor_hc_gh_skip.GH_APP_AUTH_UNAVAILABLE_SKIP_REASON`
  when the project GitHub App auth is unavailable (no host-``gh`` probe).
- PASS / FAIL / WARN normally when bearer-token REST returns shaped responses.
- HC-project-gh-secrets SKIPs on REST 403 (GitHub App auth lacks ``secrets:read`` /
  ``admin:repo`` scope) -- same UX as missing GitHub App auth.
"""

from __future__ import annotations

import textwrap
from typing import Any
from unittest.mock import patch

from yoke_core.domain.gh_rest_transport import (
    RestAuthError,
    RestResponse,
)
from yoke_core.domain.project_github_auth import (
    MissingCapability,
    ProjectGithubAuth,
)
from yoke_core.engines.doctor import (
    DoctorArgs,
    RecordCollector,
    hc_gh_orphan_detection,
    hc_orphaned_gh_issues,
    hc_project_gh_secrets,
    hc_wrong_repo_issues,
)
from yoke_core.engines.doctor_hc_gh_skip import GH_APP_AUTH_UNAVAILABLE_SKIP_REASON


def _make_conn() -> Any:
    """Disposable Postgres test DB; dropped when the conn is closed or GC'd."""
    from runtime.api.fixtures import pg_testdb
    from runtime.api.fixtures.schema_ddl import apply_fixture_ddl

    name = pg_testdb.create_test_database()
    conn = pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name,
    )
    apply_fixture_ddl(conn, textwrap.dedent("""\
        CREATE TABLE items (id INTEGER PRIMARY KEY, title TEXT, type TEXT,
            status TEXT, project_id INTEGER DEFAULT 1, github_issue TEXT);
        CREATE TABLE epic_tasks (epic_id TEXT, task_num INTEGER, title TEXT,
            github_issue TEXT, PRIMARY KEY (epic_id, task_num));
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY, slug TEXT UNIQUE, name TEXT,
            public_item_prefix TEXT DEFAULT 'YOK',
            github_repo TEXT
        );
        CREATE TABLE project_capabilities (
            project_id INTEGER, type TEXT, settings TEXT,
            PRIMARY KEY(project_id, type)
        );
    """))
    return conn


def _project_id(project: str) -> int:
    return {"yoke": 1, "externalwebapp": 2}[project]


def _seed_project(
    conn: Any, project: str, github_repo: str,
) -> None:
    conn.execute(
        "INSERT INTO projects "
        "(id, slug, name, public_item_prefix, github_repo) "
        "VALUES (%s, %s, %s, 'YOK', %s)",
        (_project_id(project), project, project.title(), github_repo),
    )


def _run_hc(fn, conn=None, **kw):
    if conn is None:
        conn = _make_conn()
    rec = RecordCollector()
    fn(conn, DoctorArgs(**kw), rec)
    return rec


def _auth(project: str = "yoke", repo: str = "upyoke/yoke") -> ProjectGithubAuth:
    return ProjectGithubAuth(
        project=project, repo=repo, token="t",
    )


def _canonical_skip(project: str = "yoke") -> str:
    return GH_APP_AUTH_UNAVAILABLE_SKIP_REASON.format(project=project)


class TestOrphanedGhIssuesNoPat:
    def test_skips_with_canonical_reason(self):
        with patch(
            "yoke_core.engines.doctor_hc_worktrees.resolve_project_github_auth",
            side_effect=MissingCapability("yoke", "no capability"),
        ):
            rec = _run_hc(hc_orphaned_gh_issues)
        assert rec.results[0].result == "SKIP"
        assert rec.results[0].detail == _canonical_skip("yoke")


class TestGhOrphanDetectionNoPat:
    def test_skips_with_canonical_reason(self):
        with patch(
            "yoke_core.engines.doctor_hc_worktrees.resolve_project_github_auth",
            side_effect=MissingCapability("yoke", "no capability"),
        ):
            rec = _run_hc(hc_gh_orphan_detection)
        assert rec.results[0].result == "SKIP"
        assert rec.results[0].detail == _canonical_skip("yoke")


class TestWrongRepoIssuesNoGitHubAuth:
    def test_skips_with_canonical_reason(self):
        with patch(
            "yoke_core.engines.doctor_hc_worktrees.resolve_project_github_auth",
            side_effect=MissingCapability("yoke", "no capability"),
        ):
            rec = _run_hc(hc_wrong_repo_issues)
        assert rec.results[0].result == "SKIP"
        assert rec.results[0].detail == _canonical_skip("yoke")


class TestProjectGhSecretsNoGitHubAuth:
    def test_skips_with_canonical_reason_on_missing_auth(self):
        conn = _make_conn()
        _seed_project(conn, "externalwebapp", "org/externalwebapp")
        with patch(
            "yoke_core.engines.doctor_hc_worktrees_gh_project.resolve_project_github_auth",
            side_effect=MissingCapability("externalwebapp", "no capability"),
        ):
            rec = _run_hc(hc_project_gh_secrets, conn, project="externalwebapp")
        assert rec.results[0].result == "SKIP"
        assert rec.results[0].detail == _canonical_skip("externalwebapp")

    def test_skips_with_canonical_reason_on_403_scope_failure(self):
        """AC-11: 403 (GitHub App auth lacks secrets:read scope) -> SKIP, not FAIL."""
        conn = _make_conn()
        _seed_project(conn, "externalwebapp", "org/externalwebapp")
        with patch(
            "yoke_core.engines.doctor_hc_worktrees_gh_project.resolve_project_github_auth",
            return_value=_auth("externalwebapp", "org/externalwebapp"),
        ), patch(
            "yoke_core.engines.doctor_hc_worktrees_gh_project.request_with_retry",
            side_effect=RestAuthError("HTTP 403: insufficient scope", status=403),
        ):
            rec = _run_hc(hc_project_gh_secrets, conn, project="externalwebapp")
        assert rec.results[0].result == "SKIP"
        assert rec.results[0].detail == _canonical_skip("externalwebapp")


class TestRestPassWithGitHubAuth:
    """With a valid GitHub App auth, the HCs PASS via REST."""

    def test_orphaned_gh_issues_passes_when_no_orphans(self):
        conn = _make_conn()
        _seed_project(conn, "yoke", "upyoke/yoke")
        conn.execute(
            "INSERT INTO items (id, title, type, status, github_issue) "
            "VALUES (1, 'Test', 'issue', 'implementing', '#100')"
        )
        with patch(
            "yoke_core.engines.doctor_hc_worktrees.resolve_project_github_auth",
            return_value=_auth(),
        ), patch(
            "yoke_core.engines.doctor_hc_worktrees_gh.resolve_project_github_auth",
            return_value=_auth(),
        ), patch(
            "yoke_core.engines.doctor_hc_worktrees_gh_rest.request_with_retry",
            return_value=RestResponse(
                status=200, headers={},
                body=[{"number": 100, "title": "linked",
                       "pull_request": None}],
            ),
        ):
            rec = _run_hc(hc_orphaned_gh_issues, conn)
        assert rec.results[0].result == "PASS"

    def test_project_gh_secrets_passes_when_secrets_present(self):
        conn = _make_conn()
        _seed_project(conn, "externalwebapp", "org/externalwebapp")
        with patch(
            "yoke_core.engines.doctor_hc_worktrees_gh_project.resolve_project_github_auth",
            return_value=_auth("externalwebapp", "org/externalwebapp"),
        ), patch(
            "yoke_core.engines.doctor_hc_worktrees_gh_project.request_with_retry",
            return_value=RestResponse(
                status=200, headers={},
                body={"total_count": 2, "secrets": [{"name": "A"}, {"name": "B"}]},
            ),
        ):
            rec = _run_hc(hc_project_gh_secrets, conn, project="externalwebapp")
        assert rec.results[0].result == "PASS"
        assert "2 secrets" in rec.results[0].detail
