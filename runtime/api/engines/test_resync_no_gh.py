"""Resync engine: read/repair behavior with no host ``gh`` binary.

Verifies the engine never probes for host ``gh`` and always routes through
the PAT-backed REST transport:

- The detect path's ``_fetch_gh_issues_per_project`` consumes
  ``request_with_retry`` directly.
- The CLI fail-closes with exit 2 when the Yoke PAT is not configured;
  the no-PAT skip print path is gone.

All tests masking ``gh`` from PATH still pass when the PAT resolves
because the engine never spawns ``gh`` in the first place.
"""

from __future__ import annotations

from io import StringIO
from unittest import mock

import pytest

import yoke_core.engines.resync as resync_mod
from yoke_core.domain import db_backend
from yoke_core.domain.gh_rest_transport import RestResponse
from yoke_core.domain.project_github_auth import (
    MissingCapability,
    MissingToken,
    ProjectGithubAuth,
)
from runtime.api.fixtures.file_test_db import init_test_db


def _fake_auth(project: str = "yoke", repo: str = "org/yoke") -> ProjectGithubAuth:
    return ProjectGithubAuth(
        project=project, repo=repo, token="t", env={"GH_TOKEN": "t"},
    )


def _mask_path(monkeypatch):
    """Mask the host so ``shutil.which('gh')`` returns None."""
    monkeypatch.setenv("PATH", "/nonexistent")


def _apply_empty_resync_schema() -> None:
    conn = db_backend.connect()
    try:
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, github_issue TEXT)")
        conn.execute(
            "CREATE TABLE epic_tasks (epic_id TEXT, task_num INTEGER, "
            "github_issue TEXT, PRIMARY KEY(epic_id, task_num))"
        )
        conn.execute("CREATE TABLE projects (id TEXT PRIMARY KEY, github_repo TEXT)")
        conn.commit()
    finally:
        conn.close()


class TestFetchUsesRestDirectly:
    """``_fetch_gh_issues_per_project`` retired ``run_gh_fn``; tests patch
    the REST surface directly.
    """

    def test_yoke_fetch_succeeds_without_host_gh(self, monkeypatch):
        _mask_path(monkeypatch)
        body = [{"number": 1, "title": "[YOK-1] ok", "labels": [],
                 "state": "OPEN", "body": ""}]
        with mock.patch(
            "yoke_core.engines.resync_detect_fetch.resolve_project_github_auth",
            return_value=_fake_auth(),
        ), mock.patch(
            "yoke_core.engines.resync_detect_fetch.request_with_retry",
            return_value=RestResponse(status=200, headers={}, body=body),
        ):
            result = resync_mod._fetch_gh_issues_per_project({"yoke": ""})
        assert result["yoke"][1]["title"] == "[YOK-1] ok"

    def test_per_project_auth_failure_sentinel(self, monkeypatch):
        _mask_path(monkeypatch)

        def fake_resolve(project, *args, **kwargs):
            if project == "yoke":
                return _fake_auth()
            raise MissingToken(project, "no token")

        yoke_body = [{"number": 1, "title": "[YOK-1] ok", "labels": [],
                        "state": "OPEN", "body": ""}]
        with mock.patch(
            "yoke_core.engines.resync_detect_fetch.resolve_project_github_auth",
            side_effect=fake_resolve,
        ), mock.patch(
            "yoke_core.engines.resync_detect_fetch.request_with_retry",
            return_value=RestResponse(status=200, headers={}, body=yoke_body),
        ):
            result = resync_mod._fetch_gh_issues_per_project(
                {"yoke": "", "buzz": "org/buzz"},
            )
        assert result["yoke"][1]["title"] == "[YOK-1] ok"
        assert result["buzz"]["_auth_error"] == "missing_token"


class TestMainFailsClosedWithoutGh:
    """The CLI fail-closes with exit 2 when Yoke PAT is missing; the
    legacy ``Note: gh CLI not available. Skipping ...`` print is gone.
    """

    def test_detect_no_pat_returns_exit_2(self, monkeypatch, tmp_path):
        _mask_path(monkeypatch)
        with init_test_db(tmp_path, apply_schema=_apply_empty_resync_schema) as db_path:
            yoke_root = str(tmp_path)
            with mock.patch(
                "yoke_core.engines.resync_detect_fetch.resolve_project_github_auth",
                side_effect=MissingCapability("yoke", "no capability"),
            ), mock.patch(
                "yoke_core.engines.resync._resolve_yoke_root",
                return_value=yoke_root,
            ), mock.patch("sys.stdout", StringIO()), mock.patch("sys.stderr", StringIO()):
                rc = resync_mod.main(["--detect-only"])
        assert rc == 2

    def test_no_legacy_skip_print_on_no_pat(self, monkeypatch, tmp_path, capsys):
        """The legacy ``gh CLI not available. Skipping`` print is gone."""
        _mask_path(monkeypatch)
        with init_test_db(tmp_path, apply_schema=_apply_empty_resync_schema) as db_path:
            yoke_root = str(tmp_path)
            with mock.patch(
                "yoke_core.engines.resync_detect_fetch.resolve_project_github_auth",
                side_effect=MissingCapability("yoke", "no capability"),
            ), mock.patch(
                "yoke_core.engines.resync._resolve_yoke_root",
                return_value=yoke_root,
            ):
                resync_mod.main(["--detect-only"])
        out = capsys.readouterr()
        # The retired legacy line must not appear in the engine output.
        assert "gh CLI not available" not in out.out
