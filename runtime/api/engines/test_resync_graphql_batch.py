"""GraphQL batch-fetch behavior for the resync engine."""

from __future__ import annotations

import re
import threading
from unittest import mock

import pytest

import yoke_core.engines.resync as resync_mod


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
            project="yoke",
            repo="bound/repository",
            token="t",
        )
        requests = []

        def fake_request(request, *, token):
            requests.append((request, token))
            return RestResponse(status=200, headers={}, body=payload)

        with (
            mock.patch(
                "yoke_core.engines.resync_detect_fetch.resolve_project_github_auth",
                return_value=auth,
            ),
            mock.patch(
                "yoke_core.engines.resync_detect_fetch.request_with_retry",
                side_effect=fake_request,
            ),
        ):
            result = resync_mod._graphql_batch_fetch([1, 2, 3])

        assert result[1]["body"] == "Body 1"
        assert result[1]["comments"] == [{"body": "c1"}]
        assert result[2]["body"] == "Body 2"
        assert 3 not in result
        assert requests[0][1] == "t"
        query = requests[0][0].body["query"]
        assert 'repository(owner: "bound", name: "repository")' in query

    def test_invalid_response_fails_closed(self):
        from yoke_core.domain.gh_rest_transport import (
            RestResponse,
            RestTransportError,
        )
        from yoke_core.domain.project_github_auth import ProjectGithubAuth

        auth = ProjectGithubAuth(project="yoke", repo="org/yoke", token="t")
        with (
            mock.patch(
                "yoke_core.engines.resync_detect_fetch.resolve_project_github_auth",
                return_value=auth,
            ),
            mock.patch(
                "yoke_core.engines.resync_detect_fetch.request_with_retry",
                return_value=RestResponse(status=200, headers={}, body="not-a-dict"),
            ),
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
            project="yoke",
            repo="org/yoke",
            token="t",
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
        with (
            mock.patch(
                "yoke_core.engines.resync_detect_fetch.resolve_project_github_auth",
                return_value=auth,
            ),
            mock.patch(
                "yoke_core.engines.resync_detect_fetch.request_with_retry",
                return_value=RestResponse(status=200, headers={}, body=payload),
            ),
        ):
            with pytest.raises(RestTransportError, match="incomplete issue data"):
                resync_mod._graphql_batch_fetch([1, 2])

    def test_multiple_batches_are_fetched_concurrently(self):
        from yoke_core.domain.gh_rest_transport import RestResponse
        from yoke_core.domain.project_github_auth import ProjectGithubAuth

        auth = ProjectGithubAuth(
            project="yoke",
            repo="org/yoke",
            token="t",
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

        with (
            mock.patch(
                "yoke_core.engines.resync_detect_fetch.resolve_project_github_auth",
                return_value=auth,
            ),
            mock.patch(
                "yoke_core.engines.resync_detect_fetch.request_with_retry",
                side_effect=fake_request,
            ),
        ):
            result = resync_mod._graphql_batch_fetch([1, 2], batch_size=1)

        assert set(result) == {1, 2}
