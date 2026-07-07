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

import json
import os
from typing import Dict, List
from unittest import mock

import pytest

import yoke_core.engines.resync as resync_mod
from yoke_core.engines.resync import PairedItem

from yoke_core.engines._resync_test_helpers import (
    populated_db,
    test_db,
)


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
                env={"GH_TOKEN": "t"},
            )

        yoke_body = [{"number": 100, "title": "[YOK-42] Test", "labels": [],
                        "state": "OPEN", "body": "Body"}]
        buzz_body = [{"number": 5, "title": "Buzz item", "labels": [],
                      "state": "CLOSED", "body": "Buzz body"}]
        responses = [
            RestResponse(status=200, headers={}, body=yoke_body),
            RestResponse(status=200, headers={}, body=buzz_body),
        ]
        with mock.patch(
            "yoke_core.engines.resync_detect_fetch.resolve_project_github_auth",
            side_effect=fake_auth,
        ), mock.patch(
            "yoke_core.engines.resync_detect_fetch.request_with_retry",
            side_effect=responses,
        ):
            result = resync_mod._fetch_gh_issues_per_project({"yoke": "", "buzz": "org/buzz"})
        assert result["yoke"][100]["title"] == "[YOK-42] Test"
        assert result["buzz"][5]["state"] == "CLOSED"

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

    def test_stage1_5_heavy_fetch_batches_default_and_project_repos(self):
        import subprocess as _sp

        paired = [
            PairedItem("YOK-42", "/tmp/042.md", 100, "backlog", "yoke", ""),
            PairedItem("YOK-77", "/tmp/077.md", 7, "backlog", "buzz", "org/buzz"),
        ]

        # On CI the yoke project's auth resolution returns empty so
        # `_resolve_default_repo_nwo` returns "" and the yoke branch is
        # skipped — mock both the default-repo resolver and the per-project
        # subprocess call so the test exercises the batching logic
        # regardless of laptop credentials. The graphql mock lives at the
        # `resync._graphql_batch_fetch` re-export because the wrapper at
        # `resync_wrappers.stage1_5_heavy_fetch` calls back into `resync`.
        def fake_subprocess(args, **kwargs):
            return _sp.CompletedProcess(args, 0, "org/buzz", "")

        with mock.patch(
            "yoke_core.engines.resync_detect_linkage._resolve_default_repo_nwo",
            return_value="upyoke/yoke",
        ), mock.patch(
            "yoke_core.engines.resync_detect_linkage.subprocess.run",
            side_effect=fake_subprocess,
        ), mock.patch(
            "yoke_core.engines.resync._graphql_batch_fetch",
            side_effect=[
                {100: {"number": 100, "body": "a", "comments": []}},
                {7: {"number": 7, "body": "b", "comments": []}},
            ],
        ) as fetch:
            result = resync_mod.stage1_5_heavy_fetch(paired, {"yoke": {}, "buzz": {}})

        assert result["yoke"][100]["body"] == "a"
        assert result["buzz"][7]["body"] == "b"
        assert fetch.call_count == 2

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


class TestGraphqlBatchFetch:
    def test_empty_inputs_return_empty_map(self):
        assert resync_mod._graphql_batch_fetch([], "owner", "repo") == {}
        assert resync_mod._graphql_batch_fetch([1], "", "repo") == {}
        assert resync_mod._graphql_batch_fetch([1], "owner", "") == {}

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
        auth = ProjectGithubAuth(project="yoke", repo="org/yoke", token="t", env={})
        with mock.patch(
            "yoke_core.engines.resync_detect_fetch.resolve_project_github_auth",
            return_value=auth,
        ), mock.patch(
            "yoke_core.engines.resync_detect_fetch.request_with_retry",
            return_value=RestResponse(status=200, headers={}, body=payload),
        ):
            result = resync_mod._graphql_batch_fetch([1, 2, 3], "owner", "repo")

        assert result[1]["body"] == "Body 1"
        assert result[1]["comments"] == [{"body": "c1"}]
        assert result[2]["body"] == "Body 2"
        assert 3 not in result

    def test_invalid_response_is_skipped(self):
        from yoke_core.domain.gh_rest_transport import RestResponse
        from yoke_core.domain.project_github_auth import ProjectGithubAuth

        auth = ProjectGithubAuth(project="yoke", repo="org/yoke", token="t", env={})
        with mock.patch(
            "yoke_core.engines.resync_detect_fetch.resolve_project_github_auth",
            return_value=auth,
        ), mock.patch(
            "yoke_core.engines.resync_detect_fetch.request_with_retry",
            return_value=RestResponse(status=200, headers={}, body="not-a-dict"),
        ):
            result = resync_mod._graphql_batch_fetch([1], "owner", "repo")
        assert result == {}
