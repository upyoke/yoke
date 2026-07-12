"""Organization-only publishing retains the authenticated user identity."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("textual")

from yoke_cli.config import github_publish, machine_config, onboard_wizard_flow
from yoke_cli.config.onboard_wizard_flow_publish import PublishFlow


class _OwnerShell(PublishFlow):
    def __init__(self, config: Path) -> None:
        self.result = SimpleNamespace(
            machine_github_api_url="https://api.github.com",
            config_path=config,
            project_publish_private=True,
            project_slug="demo",
        )
        self.prompted = False

    def _goto_input(self, *_args, **_kwargs) -> None:
        self.prompted = True

    def _goto_owner_picker_error(self, exc: BaseException) -> None:
        raise AssertionError(str(exc))


def test_org_only_picker_routes_create_to_org_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        onboard_wizard_flow,
        "fetch_repo_owners",
        lambda *_args: [
            github_publish.RepoOwner("octocat", "user"),
            github_publish.RepoOwner("acme-inc", "organization"),
        ],
    )
    monkeypatch.setattr(
        machine_config,
        "github_config",
        lambda _path: {"installations": [{
            "account_login": "ACME-INC",
            "repository_selection": "all",
            "permissions": {"administration": "write"},
            "suspended": False,
        }]},
    )
    shell = _OwnerShell(tmp_path / "config.json")
    visible = shell._fetch_repo_owners()
    assert [(owner.login, owner.kind) for owner in visible] == [
        ("acme-inc", "organization"),
    ]
    shell._owner_lookup = {owner.login.casefold(): owner for owner in visible}
    shell._on_owner_pick("ACME-INC")
    assert shell.prompted is True
    assert shell.result.project_publish_owner == "acme-inc"
    assert shell.result.project_publish_owner_login == "octocat"

    requests: list[tuple[str, str]] = []

    def request(_api_url, path, _token, *, method="GET", **_kwargs):
        requests.append((method, path))
        return {"full_name": "acme-inc/demo", "private": True}

    monkeypatch.setattr(github_publish, "_request_json", request)
    created = github_publish.create_repo(
        "https://api.github.com",
        "token",
        owner=shell.result.project_publish_owner,
        name="demo",
        user_login=shell.result.project_publish_owner_login,
        private=True,
        administration_allowed=True,
    )

    assert created["full_name"] == "acme-inc/demo"
    assert requests == [("POST", "/orgs/acme-inc/repos")]


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
