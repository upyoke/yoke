"""Private-repo picker labels and selection URLs name the same repository."""

from __future__ import annotations

import pytest

pytest.importorskip("textual")

from yoke_cli.config import github_publish
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
