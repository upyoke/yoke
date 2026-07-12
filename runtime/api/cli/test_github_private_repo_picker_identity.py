"""Private-repo picker labels and selection URLs name the same repository."""

from __future__ import annotations

import pytest

pytest.importorskip("textual")

from yoke_cli.config import github_publish
from yoke_cli.config import github_publish_repositories
from yoke_cli.config import onboard_wizard_project_screens


def test_private_repo_list_rejects_mismatched_or_malformed_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = [
        {
            "full_name": "owner/private-a",
            "clone_url": "https://github.com/owner/private-b.git",
            "private": True,
        },
        {
            "full_name": "owner/not-a-boolean",
            "clone_url": "https://github.com/owner/not-a-boolean.git",
            "private": "true",
        },
        {
            "full_name": "owner/control\nlabel",
            "clone_url": "https://github.com/owner/control-label.git",
            "private": True,
        },
        {
            "full_name": "Owner/Private-Good",
            "clone_url": "git@github.com:owner/private-good.git",
            "private": True,
        },
    ]
    monkeypatch.setattr(
        github_publish, "_request_json", lambda *_args, **_kwargs: payload,
    )

    repos = github_publish.list_user_repos(
        "https://api.github.com", "token", private_only=True,
        web_url="https://github.com",
    )
    rows = onboard_wizard_project_screens.repo_rows(repos)

    assert len(repos) == 1
    assert repos[0].full_name == "Owner/Private-Good"
    assert repos[0].clone_url == "https://github.com/Owner/Private-Good.git"
    assert [(row.label, row.value) for row in rows] == [
        ("Owner/Private-Good", "https://github.com/Owner/Private-Good.git"),
    ]


def test_private_repo_list_paginates_and_deduplicates() -> None:
    calls: list[dict[str, object]] = []
    pages = {
        1: [
            {
                "full_name": "owner/public",
                "clone_url": "https://github.com/owner/public.git",
                "private": False,
            },
            {
                "full_name": "owner/private-a",
                "clone_url": "https://github.com/owner/private-a.git",
                "private": True,
            },
        ],
        2: [
            {
                "full_name": "OWNER/PRIVATE-A",
                "clone_url": "https://github.com/owner/private-a.git",
                "private": True,
            },
            {
                "full_name": "owner/private-b",
                "clone_url": "https://github.com/owner/private-b.git",
                "private": True,
            },
        ],
        3: [],
    }

    def request(*_args, **kwargs):
        calls.append(kwargs)
        return pages[int(kwargs["query"]["page"])]

    repos = github_publish_repositories.list_user_repos(
        request,
        "https://api.github.com",
        "token",
        private_only=True,
        page_size=2,
        monotonic=lambda: 10.0,
    )

    assert [repo.full_name for repo in repos] == [
        "owner/private-a", "owner/private-b",
    ]
    assert [call["query"]["page"] for call in calls] == ["1", "2", "3"]
    assert {call["deadline"] for call in calls} == {30.0}


def test_private_repo_list_fails_closed_at_page_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        github_publish_repositories, "REPOSITORY_LIST_MAX_PAGES", 2,
    )

    with pytest.raises(github_publish.GitHubPublishError, match="bounded picker limit"):
        github_publish_repositories.list_user_repos(
            lambda *_args, **_kwargs: [{
                "full_name": "owner/private",
                "clone_url": "https://github.com/owner/private.git",
                "private": True,
            }],
            "https://api.github.com",
            "token",
            private_only=True,
            page_size=1,
            monotonic=lambda: 10.0,
        )
