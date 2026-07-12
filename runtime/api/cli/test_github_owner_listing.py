"""GitHub publish-owner pagination and identity validation."""

from __future__ import annotations

import pytest

from yoke_cli.config import github_publish


def test_owner_list_dedupes_orgs_and_rejects_conflicting_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = {
        "/user": {"login": "octocat"},
        "/user/orgs": [
            {"login": "Acme-Inc"},
            {"login": "acme-inc"},
            {"login": "bad/org"},
        ],
    }
    monkeypatch.setattr(
        github_publish,
        "_request_json",
        lambda _api, path, _token, **_kwargs: responses[path],
    )
    owners = github_publish.list_repo_owners("https://api.github.com", "token")
    assert [(owner.login, owner.kind) for owner in owners] == [
        ("octocat", "user"),
        ("Acme-Inc", "organization"),
    ]

    responses["/user/orgs"] = [{"login": "OCTOCAT"}]
    with pytest.raises(github_publish.GitHubPublishError, match="both user"):
        github_publish.list_repo_owners("https://api.github.com", "token")


def test_owner_list_reaches_organizations_after_first_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_page = [{"login": f"org-{index:03d}"} for index in range(100)]

    def request(_api, path, _token, **kwargs):
        if path == "/user":
            return {"login": "octocat"}
        return (
            first_page
            if kwargs["query"]["page"] == "1"
            else [{"login": "older-target-org"}]
        )

    monkeypatch.setattr(github_publish, "_request_json", request)
    owners = github_publish.list_repo_owners("https://api.github.com", "token")

    assert owners[-1] == github_publish.RepoOwner(
        "older-target-org", "organization",
    )


def test_owner_list_full_duplicate_page_does_not_end_pagination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages: list[str] = []

    def request(_api, path, _token, **kwargs):
        if path == "/user":
            return {"login": "octocat"}
        page = kwargs["query"]["page"]
        pages.append(page)
        if page == "1":
            return [{"login": "duplicate-org"}] * 100
        return [{"login": "later-org"}]

    monkeypatch.setattr(github_publish, "_request_json", request)

    owners = github_publish.list_repo_owners(
        "https://api.github.com", "token",
    )

    assert pages == ["1", "2"]
    assert [owner.login for owner in owners] == [
        "octocat", "duplicate-org", "later-org",
    ]


def test_owner_list_shares_one_aggregate_deadline_across_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict] = []

    def monotonic() -> float:
        return 100.0

    def request(_api, path, _token, **kwargs):
        calls.append({"path": path, **kwargs})
        if path == "/user":
            return {"login": "octocat"}
        return []

    monkeypatch.setattr(github_publish, "_request_json", request)

    github_publish.list_repo_owners(
        "https://api.github.com", "token", monotonic=monotonic,
    )

    assert len(calls) == 2
    assert {call["deadline"] for call in calls} == {
        100.0 + github_publish.OWNER_LIST_DEADLINE_SECONDS
    }
    assert all(call["monotonic"] is monotonic for call in calls)
