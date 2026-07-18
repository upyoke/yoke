"""Operation-wide budgets for GitHub App repository binding verification."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse

import pytest

from runtime.api.domain.github_app_server_verification_test_support import (
    FakeGitHubResponse,
    github_app_control_plane_config,
    github_app_installation_payload,
)
from yoke_core.domain.github_app_binding_verification_budget import (
    GitHubBindingVerificationBudget,
)
from yoke_core.domain.github_app_server_installation import (
    fetch_server_app_installation,
)
from yoke_core.domain.github_app_user_verification import (
    GitHubUserVerificationError,
    verify_project_github_binding,
)


class _MutableClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _budget(
    *,
    timeout_seconds: float = 30.0,
    max_requests: int = 64,
    max_rows: int = 10_000,
    max_bytes: int = 32 * 1024 * 1024,
    clock=None,
) -> GitHubBindingVerificationBudget:
    return GitHubBindingVerificationBudget.for_operation(
        timeout_seconds,
        max_requests=max_requests,
        max_rows=max_rows,
        max_bytes=max_bytes,
        clock=clock or _MutableClock(),
    )


def _verify(*, opener, budget, server_fetcher=None):
    return verify_project_github_binding(
        installation_id="12345",
        repository_id="4567",
        expected_github_repo="example-org/externalwebapp",
        expected_api_url="https://api.github.com",
        github_user_access_token="token-must-never-escape",
        opener=opener,
        control_plane_config=github_app_control_plane_config(),
        server_installation_opener=opener,
        server_installation_fetcher=server_fetcher,
        verification_budget=budget,
    )


def test_one_budget_allows_normal_late_page_binding_proof():
    events = []
    clock = _MutableClock()

    def opener(request, timeout):
        path = urllib.parse.urlsplit(request.full_url).path
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)
        page = int(query.get("page", ["1"])[0])
        events.append((path, page, timeout))
        clock.advance(0.5)
        if path == "/user":
            body = {"id": 77, "login": "octocat"}
        elif path == "/user/installations":
            body = {
                "installations": (
                    [{"id": value} for value in range(1, 101)]
                    if page == 1
                    else [github_app_installation_payload()]
                )
            }
        elif path == "/app/installations/12345":
            body = github_app_installation_payload()
        else:
            assert path == "/user/installations/12345/repositories"
            body = {
                "repositories": (
                    [{"id": value} for value in range(1, 101)]
                    if page == 1
                    else [
                        {
                            "id": 4567,
                            "full_name": "Example-Org/ExternalWebapp",
                            "default_branch": "trunk",
                            "owner": {"id": 9988},
                        }
                    ]
                )
            }
        return FakeGitHubResponse(body, request.full_url)

    def server_fetcher(**kwargs):
        return fetch_server_app_installation(
            **kwargs,
            jwt_factory=lambda **values: "server-app-jwt",
        )

    budget = _budget(
        timeout_seconds=10.0,
        max_requests=6,
        max_rows=202,
        clock=clock,
    )
    verified = _verify(
        opener=opener,
        budget=budget,
        server_fetcher=server_fetcher,
    )

    assert verified.github_repo == "Example-Org/ExternalWebapp"
    assert budget.requests_used == 6
    assert budget.rows_used == 202
    assert [event[:2] for event in events] == [
        ("/user", 1),
        ("/user/installations", 1),
        ("/user/installations", 2),
        ("/app/installations/12345", 1),
        ("/user/installations/12345/repositories", 1),
        ("/user/installations/12345/repositories", 2),
    ]
    assert [event[2] for event in events] == pytest.approx(
        [10.0, 9.5, 9.0, 8.5, 8.0, 7.5]
    )


def test_request_budget_stops_pagination_before_an_extra_request():
    calls = []

    def opener(request, timeout):
        del timeout
        path = urllib.parse.urlsplit(request.full_url).path
        calls.append(path)
        if path == "/user":
            body = {"id": 77, "login": "octocat"}
        else:
            body = {"installations": [{"id": value} for value in range(1, 101)]}
        return FakeGitHubResponse(body, request.full_url)

    with pytest.raises(GitHubUserVerificationError, match="request budget"):
        _verify(opener=opener, budget=_budget(max_requests=2))

    assert calls == ["/user", "/user/installations"]


def test_row_budget_rejects_a_page_before_selected_metadata_is_used():
    calls = []

    def opener(request, timeout):
        del timeout
        path = urllib.parse.urlsplit(request.full_url).path
        calls.append(path)
        body = (
            {"id": 77, "login": "octocat"}
            if path == "/user"
            else {
                "installations": [
                    github_app_installation_payload(),
                    *({"id": value} for value in range(1, 11)),
                ]
            }
        )
        return FakeGitHubResponse(body, request.full_url)

    with pytest.raises(GitHubUserVerificationError, match="row budget"):
        _verify(opener=opener, budget=_budget(max_rows=10))

    assert calls == ["/user", "/user/installations"]


def test_cumulative_byte_budget_rejects_individually_valid_responses():
    user_body = {"id": 77, "login": "octocat"}
    page_body = {"installations": [{"id": value} for value in range(1, 101)]}
    user_size = len(json.dumps(user_body).encode("utf-8"))
    page_size = len(json.dumps(page_body).encode("utf-8"))
    calls = []

    def opener(request, timeout):
        del timeout
        path = urllib.parse.urlsplit(request.full_url).path
        calls.append(path)
        body = user_body if path == "/user" else page_body
        return FakeGitHubResponse(body, request.full_url)

    budget = _budget(max_bytes=user_size + page_size - 1)
    with pytest.raises(GitHubUserVerificationError, match="byte budget"):
        _verify(opener=opener, budget=budget)

    assert page_size < budget.max_bytes
    assert calls == ["/user", "/user/installations"]


def test_deadline_uses_remaining_operation_time_and_rejects_late_response():
    clock = _MutableClock()
    observed_timeouts = []

    def opener(request, timeout):
        observed_timeouts.append(timeout)
        clock.advance(1.1)
        return FakeGitHubResponse({"id": 77, "login": "octocat"}, request.full_url)

    with pytest.raises(GitHubUserVerificationError, match="deadline exceeded"):
        _verify(
            opener=opener,
            budget=_budget(timeout_seconds=1.0, clock=clock),
        )

    assert observed_timeouts == [1.0]


def test_user_verification_network_error_cannot_echo_token_detail():
    secret = "token-must-never-escape"

    def unavailable(request, timeout):
        del request, timeout
        raise urllib.error.URLError(f"transport reflected {secret}")

    with pytest.raises(GitHubUserVerificationError, match="was unavailable") as error:
        _verify(opener=unavailable, budget=_budget())

    assert secret not in str(error.value)
