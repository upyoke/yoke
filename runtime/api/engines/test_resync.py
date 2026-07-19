"""Tests for resync engine: helpers, stage1 fetch, and GraphQL batching.

Repair tests live in test_resync_repair.py.
Stage-2 compare and normalize tests live in test_resync_compare.py.
Doctor-format / CLI / exit-code tests live in test_resync_cli.py.
Fail-closed GitHub-auth regressions live in test_resync_auth.py.

Pytest fixtures (test_db, populated_db) are shared via
_resync_test_helpers (private module).
No live ``gh`` calls are made.
"""

from __future__ import annotations

import re
import threading
from unittest import mock

import pytest

import yoke_core.engines.resync as resync_mod
from yoke_core.engines.resync import PairedItem
from yoke_core.engines._resync_test_helpers import (
    populated_db as populated_db,
    test_db as test_db,
)

TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


class TestHelpers:
    def test_resolve_yoke_root_normalizes_repo_root_env(self, tmp_path, monkeypatch):
        repo_root = tmp_path / "repo"
        state_dir = repo_root / ".yoke"
        state_dir.mkdir(parents=True)
        monkeypatch.setenv("YOKE_ROOT", str(repo_root))
        assert resync_mod._resolve_yoke_root() == str(state_dir)

    def test_resolve_yoke_root_preserves_project_state_dir_env(self, tmp_path, monkeypatch):
        state_dir = tmp_path / "repo" / ".yoke"
        state_dir.mkdir(parents=True)
        monkeypatch.setenv("YOKE_ROOT", str(state_dir))
        assert resync_mod._resolve_yoke_root() == str(state_dir)

    def test_resolve_yoke_root_uses_python_path_helper(self, monkeypatch):
        monkeypatch.delenv("YOKE_ROOT", raising=False)
        with mock.patch("yoke_core.engines.resync.resolve_worktree_yoke_root", return_value="/tmp/resolved-root"):
            assert resync_mod._resolve_yoke_root() == "/tmp/resolved-root"

    def test_resolve_yoke_root_falls_back_to_repo_state_dir(self, monkeypatch):
        monkeypatch.delenv("YOKE_ROOT", raising=False)
        with mock.patch("yoke_core.engines.resync.resolve_worktree_yoke_root", side_effect=RuntimeError("boom")):
            resolved = resync_mod._resolve_yoke_root()
        assert resolved.endswith("/runtime")

    def test_fetch_gh_issues_per_project_parses_multiple_projects(self):
        """REST fetch shapes per-project issue maps for yoke + non-yoke repos."""
        from yoke_core.domain.gh_rest_transport import RestResponse
        from yoke_core.domain.project_github_auth import ProjectGithubAuth

        def fake_auth(project, *args, **kwargs):
            return ProjectGithubAuth(
                project=project, repo=f"org/{project}", token="t",
            )

        yoke_body = [{"number": 100, "title": "[YOK-42] Test", "labels": [],
                        "state": "OPEN", "body": "Body"}]
        externalwebapp_body = [{"number": 5, "title": "ExternalWebapp item", "labels": [],
                      "state": "CLOSED", "body": "ExternalWebapp body"}]
        responses = [
            RestResponse(status=200, headers={}, body=yoke_body),
            RestResponse(status=200, headers={}, body=externalwebapp_body),
        ]
        with mock.patch(
            "yoke_core.engines.resync_detect_fetch.resolve_project_github_auth",
            side_effect=fake_auth,
        ), mock.patch(
            "yoke_core.engines.resync_detect_fetch.request_with_retry",
            side_effect=responses,
        ):
            result = resync_mod._fetch_gh_issues_per_project({"yoke", "externalwebapp"})
        assert result["yoke"][100]["title"] == "[YOK-42] Test"
        assert result["externalwebapp"][5]["state"] == "CLOSED"

    def test_fetch_uses_repo_from_same_resolution_as_token(self):
        from yoke_core.domain.gh_rest_transport import RestResponse
        from yoke_core.domain.project_github_auth import ProjectGithubAuth

        auth = ProjectGithubAuth(
            project="yoke", repo="bound/repository", token="bound-token",
        )
        calls = []

        def fake_request(request, *, token):
            calls.append((request, token))
            return RestResponse(status=200, headers={}, body=[])

        with mock.patch(
            "yoke_core.engines.resync_detect_fetch.resolve_project_github_auth",
            return_value=auth,
        ), mock.patch(
            "yoke_core.engines.resync_detect_fetch.request_with_retry",
            side_effect=fake_request,
        ):
            result = resync_mod._fetch_gh_issues_per_project(
                {"yoke"},
            )

        assert result == {"yoke": {}}
        assert calls[0][0].path == "/repos/bound/repository/issues"
        assert calls[0][1] == "bound-token"

class TestStage1:
    def test_stage1_linkage_builds_pairs_local_orphans_and_gh_orphans(self, populated_db, tmp_path):
        yoke_root = tmp_path / "state"
        (yoke_root / "backlog").mkdir(parents=True)
        gh_map = {
            "yoke": {
                100: {"number": 100, "title": "[YOK-42] Test item", "labels": [], "state": "OPEN", "body": ""},
                102: {"number": 102, "title": "[YOK-1246] Epic parent", "labels": [], "state": "OPEN", "body": ""},
                200: {"number": 200, "title": "[YOK-1246] Task 001 Task one", "labels": [], "state": "OPEN", "body": ""},
                999: {"number": 999, "title": "[YOK-999] Orphan", "labels": [], "state": "OPEN", "body": ""},
            }
        }
        with mock.patch("yoke_core.engines.resync._fetch_gh_issues_per_project", return_value=gh_map):
            paired, local_orphans, gh_orphans, gh_by_project = resync_mod.stage1_linkage(
                populated_db,
                str(yoke_root),
            )

        paired_ids = {item.id for item in paired}
        local_orphan_ids = {item_id for item_id, *_ in local_orphans}
        assert "YOK-42" in paired_ids
        assert "YOK-1246" in paired_ids
        assert "1246/task-001" in paired_ids
        assert "YOK-43" in local_orphan_ids
        assert gh_orphans == [(999, "[YOK-999] Orphan", "OPEN", "yoke")]
        assert gh_by_project["yoke"][100]["title"] == "[YOK-42] Test item"

    def test_stage1_5_heavy_fetch_uses_resolved_repo_and_token_together(self):
        paired = [
            PairedItem(
                TEST_ITEM_REF, "/tmp/042.md", 100, "backlog", "yoke", "stale/yoke",
            ),
            PairedItem(
                "YOK-77", "/tmp/077.md", 7, "backlog", "externalwebapp", "stale/externalwebapp",
            ),
        ]

        from yoke_core.domain.project_github_auth import ProjectGithubAuth

        auth_by_project = {
            project: ProjectGithubAuth(
                project=project,
                repo=f"bound/{project}",
                token=f"{project}-token",
            )
            for project in ("yoke", "externalwebapp")
        }
        with mock.patch(
            "yoke_core.engines.resync_detect_linkage.resolve_project_github_auth",
            side_effect=lambda project, **_kwargs: auth_by_project[project],
        ) as auth_resolver, mock.patch(
            "yoke_core.engines.resync._graphql_batch_fetch",
            side_effect=[
                {100: {"number": 100, "body": "a", "comments": []}},
                {7: {"number": 7, "body": "b", "comments": []}},
            ],
        ) as fetch:
            result = resync_mod.stage1_5_heavy_fetch(paired, {"yoke": {}, "externalwebapp": {}})

        assert result["yoke"][100]["body"] == "a"
        assert result["externalwebapp"][7]["body"] == "b"
        assert fetch.call_count == 2
        from yoke_contracts.github_app_installation_permissions import (
            GITHUB_ISSUES_READ_PERMISSION_LEVELS,
        )

        assert [
            call.kwargs["required_permissions"]
            for call in auth_resolver.call_args_list
        ] == [GITHUB_ISSUES_READ_PERMISSION_LEVELS] * 2
        for call, project in zip(fetch.call_args_list, ("yoke", "externalwebapp")):
            assert call.kwargs["project"] == project
            assert call.kwargs["auth"] is auth_by_project[project]
            assert call.kwargs["auth"].repo == f"bound/{project}"
            assert call.kwargs["auth"].token == f"{project}-token"

    def test_stage1_linkage_skips_marked_github_orphans(self, populated_db, tmp_path):
        yoke_root = tmp_path / "state"
        (yoke_root / "backlog").mkdir(parents=True)
        gh_map = {
            "yoke": {
                100: {"number": 100, "title": "[YOK-9999] Test item", "labels": [], "state": "OPEN", "body": ""},
                999: {
                    "number": 999,
                    "title": "[YOK-999] Orphan",
                    "labels": [{"name": "yoke:orphan"}],
                    "state": "OPEN",
                    "body": "",
                },
            }
        }
        with mock.patch("yoke_core.engines.resync._fetch_gh_issues_per_project", return_value=gh_map):
            _, _, gh_orphans, _ = resync_mod.stage1_linkage(populated_db, str(yoke_root))

        assert gh_orphans == []

    def test_stage1_linkage_scopes_fetch_and_rows_to_requested_project(
        self, populated_db, tmp_path,
    ):
        from runtime.api.fixtures.file_test_db import connect_test_db

        conn = connect_test_db(populated_db)
        conn.execute(
            "INSERT INTO items "
            "(id, title, status, priority, type, source, spec, frozen, "
            "github_issue, project_id, project_sequence, created_at, updated_at) "
            "VALUES (44, 'External item', 'idea', 'medium', 'issue', 'manual', "
            "'Body', 0, '#7', 2, 1, '2026-01-01', '2026-01-01')"
        )
        conn.commit()
        conn.close()
        yoke_root = tmp_path / "state"
        yoke_root.mkdir()
        observed_rosters = []

        def fake_fetch(projects):
            observed_rosters.append(set(projects))
            return {
                "externalwebapp": {
                    7: {
                        "number": 7,
                        "title": "[YOK-44] External item",
                        "labels": [],
                        "state": "OPEN",
                        "body": "Body",
                    },
                },
            }

        with mock.patch(
            "yoke_core.engines.resync._fetch_gh_issues_per_project",
            side_effect=fake_fetch,
        ):
            paired, local_orphans, gh_orphans, states = (
                resync_mod.stage1_linkage(
                    populated_db,
                    str(yoke_root),
                    project="externalwebapp",
                )
            )

        assert observed_rosters == [{"externalwebapp"}]
        assert [item.id for item in paired] == ["YOK-44"]
        assert local_orphans == []
        assert gh_orphans == []
        assert set(states) == {"externalwebapp"}


class TestGraphqlBatchFetch:
    def test_empty_inputs_return_empty_map(self):
        assert resync_mod._graphql_batch_fetch([]) == {}

    def test_parses_graphql_payload(self):
        from yoke_core.domain.gh_rest_transport import RestResponse
        from yoke_core.domain.project_github_auth import ProjectGithubAuth

        payload = {
            "data": {
                "repository": {
                    "issue_1": {
                        "number": 1,
                        "body": "Body 1",
                        "comments": {"nodes": [{"body": "c1"}]},
                    },
                    "issue_2": {
                        "number": 2,
                        "body": "Body 2",
                        "comments": {"nodes": []},
                    },
                    "issue_3": None,
                }
            }
        }
        auth = ProjectGithubAuth(
            project="yoke", repo="bound/repository", token="t",
        )
        requests = []

        def fake_request(request, *, token):
            requests.append((request, token))
            return RestResponse(status=200, headers={}, body=payload)

        with mock.patch(
            "yoke_core.engines.resync_detect_fetch.resolve_project_github_auth",
            return_value=auth,
        ), mock.patch(
            "yoke_core.engines.resync_detect_fetch.request_with_retry",
            side_effect=fake_request,
        ):
            result = resync_mod._graphql_batch_fetch([1, 2, 3])

        assert result[1]["body"] == "Body 1"
        assert result[1]["comments"] == [{"body": "c1"}]
        assert result[2]["body"] == "Body 2"
        assert 3 not in result
        assert requests[0][1] == "t"
        assert 'repository(owner: "bound", name: "repository")' in (
            requests[0][0].body["query"]
        )

    def test_invalid_response_fails_closed(self):
        from yoke_core.domain.gh_rest_transport import (
            RestResponse,
            RestTransportError,
        )
        from yoke_core.domain.project_github_auth import ProjectGithubAuth

        auth = ProjectGithubAuth(project="yoke", repo="org/yoke", token="t")
        with mock.patch(
            "yoke_core.engines.resync_detect_fetch.resolve_project_github_auth",
            return_value=auth,
        ), mock.patch(
            "yoke_core.engines.resync_detect_fetch.request_with_retry",
            return_value=RestResponse(status=200, headers={}, body="not-a-dict"),
        ):
            with pytest.raises(RestTransportError, match="invalid payload"):
                resync_mod._graphql_batch_fetch([1])

    def test_incomplete_response_fails_closed(self):
        from yoke_core.domain.gh_rest_transport import (
            RestResponse,
            RestTransportError,
        )
        from yoke_core.domain.project_github_auth import ProjectGithubAuth

        auth = ProjectGithubAuth(
            project="yoke", repo="org/yoke", token="t",
        )
        payload = {
            "data": {
                "repository": {
                    "issue_1": {
                        "number": 1,
                        "body": "Body 1",
                        "comments": {"nodes": []},
                    },
                },
            },
        }
        with mock.patch(
            "yoke_core.engines.resync_detect_fetch.resolve_project_github_auth",
            return_value=auth,
        ), mock.patch(
            "yoke_core.engines.resync_detect_fetch.request_with_retry",
            return_value=RestResponse(status=200, headers={}, body=payload),
        ):
            with pytest.raises(RestTransportError, match="incomplete issue data"):
                resync_mod._graphql_batch_fetch([1, 2])

    def test_multiple_batches_are_fetched_concurrently(self):
        from yoke_core.domain.gh_rest_transport import RestResponse
        from yoke_core.domain.project_github_auth import ProjectGithubAuth

        auth = ProjectGithubAuth(
            project="yoke", repo="org/yoke", token="t",
        )
        both_started = threading.Event()
        starts_lock = threading.Lock()
        starts = 0

        def fake_request(request, *, token):
            nonlocal starts
            query = request.body["query"]
            number = int(re.search(r"issue_(\d+):", query).group(1))
            with starts_lock:
                starts += 1
                if starts == 2:
                    both_started.set()
            assert both_started.wait(timeout=1)
            return RestResponse(
                status=200,
                headers={},
                body={
                    "data": {
                        "repository": {
                            f"issue_{number}": {
                                "number": number,
                                "body": f"Body {number}",
                                "comments": {"nodes": []},
                            },
                        },
                    },
                },
            )

        with mock.patch(
            "yoke_core.engines.resync_detect_fetch.resolve_project_github_auth",
            return_value=auth,
        ), mock.patch(
            "yoke_core.engines.resync_detect_fetch.request_with_retry",
            side_effect=fake_request,
        ):
            result = resync_mod._graphql_batch_fetch([1, 2], batch_size=1)

        assert set(result) == {1, 2}
