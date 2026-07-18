"""Resync behavior when a GitHub project read is unavailable."""

# Imported pytest fixtures intentionally share names with test parameters.
# ruff: noqa: F811

from __future__ import annotations

from unittest import mock

import pytest

import yoke_core.engines.resync as resync_mod
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain.gh_rest_transport import RestNetworkError, RestResponse
from yoke_core.domain.project_github_auth import (
    MissingAppCredentials,
    MissingCapability,
    MissingRepoBinding,
    ProjectGithubAuth,
)
from yoke_core.engines._resync_test_helpers import (
    populated_db,  # noqa: F401 — imported pytest fixture
    test_db,  # noqa: F401 — imported pytest fixture
)

TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


def _resolved_auth(
    token: str = "test-token",
    project: str = "yoke",
) -> ProjectGithubAuth:
    return ProjectGithubAuth(
        project=project,
        repo=f"org/{project}",
        token=token,
    )


class TestHeavyFetchUnavailable:
    def test_compare_never_uses_same_issue_number_from_another_project(
        self, populated_db,
    ):
        paired = [
            resync_mod.PairedItem(
                TEST_ITEM_REF, "/tmp/042.md", 100, "backlog", "externalwebapp", "",
            ),
        ]
        light = {
            "externalwebapp": {},
            "yoke": {
                100: {
                    "number": 100,
                    "title": f"[{TEST_ITEM_REF}] Unrelated repository issue",
                    "labels": [],
                    "state": "CLOSED",
                    "body": "unrelated body",
                },
            },
        }

        assert resync_mod.stage2_compare(
            paired, light, {}, populated_db,
        ) == []

    def test_graphql_transport_failure_is_explicit_and_suppresses_drift(
        self, populated_db,
    ):
        paired = [
            resync_mod.PairedItem(
                TEST_ITEM_REF, "/tmp/042.md", 100, "backlog", "yoke", "stale/repo",
            ),
        ]
        light = {
            "yoke": {
                100: {
                    "number": 100,
                    "title": f"[{TEST_ITEM_REF}] Incorrect title",
                    "labels": [],
                    "state": "CLOSED",
                    "body": "incorrect body",
                },
            },
        }
        with mock.patch(
            "yoke_core.engines.resync_detect_linkage.resolve_project_github_auth",
            return_value=_resolved_auth(),
        ), mock.patch(
            "yoke_core.engines.resync._graphql_batch_fetch",
            side_effect=RestNetworkError("network down"),
        ):
            heavy = resync_mod.stage1_5_heavy_fetch(paired, light)

        assert heavy["yoke"]["_github_unavailable"] == "true"
        assert heavy["yoke"]["_unavailable_stage"] == "graphql"
        assert heavy["yoke"] != {}
        assert resync_mod.stage2_compare(
            paired, light, heavy, populated_db,
        ) == []

    def test_fix_mode_never_repairs_when_graphql_read_is_unavailable(
        self, tmp_path, capsys,
    ):
        paired = [
            resync_mod.PairedItem(
                TEST_ITEM_REF, "/tmp/042.md", 100, "backlog", "externalwebapp", "",
            ),
        ]
        light = {
            "externalwebapp": {
                100: {
                    "number": 100,
                    "title": f"[{TEST_ITEM_REF}] title",
                    "labels": [],
                    "state": "OPEN",
                    "body": "",
                },
            },
        }
        unavailable = {
            "_github_unavailable": "true",
            "_unavailable_code": "transport_failure",
            "_unavailable_stage": "graphql",
            "_repair_hint": "retry network access",
        }
        with mock.patch(
            "yoke_core.engines.resync._resolve_yoke_root",
            return_value=str(tmp_path),
        ), mock.patch(
            "yoke_core.engines.resync.stage1_linkage",
            return_value=(paired, [], [], light),
        ), mock.patch(
            "yoke_core.engines.resync.stage1_5_heavy_fetch",
            return_value={"externalwebapp": unavailable},
        ), mock.patch(
            "yoke_core.engines.resync.stage2_compare",
            return_value=[],
        ), mock.patch(
            "yoke_core.engines.resync._repair_drift",
        ) as repair:
            rc = resync_mod.main(["--fix"])

        assert rc == 1
        assert "drift comparison and repair skipped" in capsys.readouterr().out
        repair.assert_not_called()


class TestWrapperPropagation:
    def test_fetch_wrapper_propagates_yoke_auth_error(self):
        with mock.patch(
            "yoke_core.engines.resync_detect_fetch.resolve_project_github_auth",
            side_effect=MissingAppCredentials(
                "yoke", "App credentials unavailable",
            ),
        ):
            with pytest.raises(MissingAppCredentials):
                resync_mod._fetch_gh_issues_per_project({"yoke"})

    def test_linkage_wrapper_propagates_yoke_auth_error(
        self, populated_db, tmp_path,
    ):
        yoke_root = tmp_path / "state"
        (yoke_root / "backlog").mkdir(parents=True)
        with mock.patch(
            "yoke_core.engines.resync_detect_fetch.resolve_project_github_auth",
            side_effect=MissingCapability("yoke", "no yoke capability"),
        ):
            with pytest.raises(MissingCapability):
                resync_mod.stage1_linkage(populated_db, str(yoke_root))


class TestEngineMultiProjectPartialAuthFailure:
    def test_continues_healthy_project_without_orphans_for_failed_project(
        self, populated_db, tmp_path, monkeypatch, capsys,
    ):
        yoke_root = tmp_path / "data"
        yoke_root.mkdir(parents=True)
        monkeypatch.setenv("YOKE_ROOT", str(yoke_root))

        conn = connect_test_db(populated_db)
        conn.execute(
            "INSERT INTO projects "
            "(id, slug, name, default_branch, created_at, "
            "github_repo, public_item_prefix) "
            "VALUES (2, 'externalwebapp', 'ExternalWebapp', 'main', "
            "'2026-01-01T00:00:00Z', 'org/externalwebapp', 'EXT') "
            "ON CONFLICT (id) DO UPDATE SET "
            "slug = excluded.slug, name = excluded.name, "
            "github_repo = excluded.github_repo"
        )
        conn.execute(
            "INSERT INTO items "
            "(id, title, status, priority, type, source, spec, frozen, "
            "github_issue, project_id, project_sequence, created_at, updated_at) "
            "VALUES (500, 'ExternalWebapp item', 'idea', 'medium', 'issue', 'manual', "
            "'ExternalWebapp body', 0, '#500', 2, 1, '2026-01-01', '2026-01-01')"
        )
        conn.commit()
        conn.close()

        def fake_resolve(project, **kwargs):
            if project == "yoke":
                return _resolved_auth("yoke-token", "yoke")
            raise MissingRepoBinding(
                project, f"repository is not bound for '{project}'",
            )

        yoke_issues = RestResponse(
            status=200,
            headers={},
            body=[{
                "number": 100,
                "title": f"[{TEST_ITEM_REF}] Test item",
                "labels": [],
                "state": "OPEN",
                "body": "",
            }],
        )
        with mock.patch(
            "yoke_core.engines.resync_runtime.resolve_project_github_auth",
            side_effect=fake_resolve,
        ), mock.patch(
            "yoke_core.engines.resync_detect_fetch.resolve_project_github_auth",
            side_effect=fake_resolve,
        ), mock.patch(
            "yoke_core.engines.resync_detect_fetch.request_with_retry",
            return_value=yoke_issues,
        ):
            rc = resync_mod.main(["--detect-only"])

        out = capsys.readouterr().out
        assert rc == 1
        assert "externalwebapp" in out and "missing_repo_binding" in out
        assert "project=externalwebapp" not in out
        assert "Summary:" in out
