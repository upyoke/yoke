"""Repository-access refresh authority coverage for project onboarding."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoke_cli.config import onboard_project_github_inputs
from yoke_cli.config import project_onboard_progress
from yoke_cli.config.project_publish_support import PublishRequest


def test_repository_refresh_uses_selected_service_authority(monkeypatch) -> None:
    status_kwargs: dict = {}
    monkeypatch.setattr(
        project_onboard_progress.github_machine,
        "status",
        lambda **kwargs: status_kwargs.update(kwargs) or {"ok": True},
    )
    monkeypatch.setattr(
        project_onboard_progress.machine_config,
        "github_config",
        lambda _path: {"repositories": [{
            "installation_id": 123,
            "repository_id": 456,
            "full_name": "owner/demo",
        }]},
    )

    repository = project_onboard_progress.refresh_github_repository_access(
        "/tmp/config.json",
        "owner/demo",
        service_api_url="https://team.yoke.example",
    )

    assert repository["repository_id"] == 456
    assert status_kwargs["service_api_url"] == "https://team.yoke.example"


def test_resumed_exact_repository_identity_rejects_live_drift(monkeypatch) -> None:
    monkeypatch.setattr(
        onboard_project_github_inputs.github_machine,
        "status",
        lambda **_kwargs: {
            "identity": {"checked": True, "ok": True},
            "access": {"repo_listing_ok": True},
        },
    )
    monkeypatch.setattr(
        onboard_project_github_inputs.machine_config,
        "github_config",
        lambda _path: {
            "repositories": [{
                "installation_id": 123,
                "repository_id": 999,
                "full_name": "owner/demo",
            }],
            "installations": [{
                "installation_id": 123,
                "suspended": False,
            }],
        },
    )

    with pytest.raises(
        onboard_project_github_inputs.MachineGitHubInputError,
        match="identity changed",
    ):
        onboard_project_github_inputs.hydrate_machine_github_inputs(
            {
                "github_adoption": "app-binding",
                "github_repo": "owner/demo",
                "github_repository_id": 456,
                "github_installation_id": 123,
            },
            "/tmp/config.json",
        )


def test_future_publish_hydration_does_not_require_target_to_exist(
    monkeypatch,
) -> None:
    live_checks: list[str] = []
    monkeypatch.setattr(
        onboard_project_github_inputs.github_machine,
        "status",
        lambda **_kwargs: live_checks.append("status"),
    )
    monkeypatch.setattr(
        onboard_project_github_inputs.github_local_user_access,
        "access_token",
        lambda **_kwargs: SimpleNamespace(access_token="short-lived"),
    )
    monkeypatch.setattr(
        onboard_project_github_inputs.machine_config,
        "github_config",
        lambda _path: {
            "api_url": "https://api.github.com",
            "web_url": "https://github.com",
            "repositories": [],
        },
    )
    publish = PublishRequest(
        owner="octocat",
        name="future",
        user_login="octocat",
        token=None,
        use_machine_github=True,
        create_repository=True,
    )

    hydrated = onboard_project_github_inputs.hydrate_machine_github_inputs(
        {
            "github_adoption": "app-binding",
            "github_repo": "octocat/future",
            "github_repository_id": None,
            "github_installation_id": None,
            "publish": publish,
        },
        "/tmp/config.json",
    )

    assert hydrated["publish"].token == "short-lived"
    assert live_checks == []


def test_mutated_repository_replaces_identity_from_a_different_source(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        project_onboard_progress.github_machine,
        "status",
        lambda **_kwargs: {"ok": True},
    )
    monkeypatch.setattr(
        project_onboard_progress.machine_config,
        "github_config",
        lambda _path: {"repositories": [{
            "installation_id": 7,
            "repository_id": 88,
            "full_name": "octocat/widgets",
        }]},
    )
    adoption = {
        "choice": "app-binding",
        "github_repo": "source/widgets",
        "repository_id": 41,
        "installation_id": 5,
        "binding": {
            "repo": "source/widgets",
            "repository_id": 41,
            "installation_id": 5,
        },
    }

    project_onboard_progress.record_mutated_repository(
        adoption,
        "octocat/widgets",
        "/tmp/config.json",
    )

    assert adoption["github_repo"] == "octocat/widgets"
    assert adoption["repository_id"] == 88
    assert adoption["installation_id"] == 7
    assert adoption["binding"] == {
        "repo": "octocat/widgets",
        "repository_id": 88,
        "installation_id": 7,
    }


def test_backlog_only_stale_identity_performs_zero_live_github_calls(
    monkeypatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        onboard_project_github_inputs.github_machine,
        "status",
        lambda **_kwargs: calls.append("status"),
    )
    monkeypatch.setattr(
        onboard_project_github_inputs.machine_config,
        "github_config",
        lambda _path: calls.append("config") or {},
    )
    inputs = {
        "github_adoption": "backlog-only",
        "github_repo": "owner/demo",
        "github_repository_id": 456,
        "github_installation_id": 123,
    }

    assert onboard_project_github_inputs.hydrate_machine_github_inputs(
        inputs, "/tmp/config.json",
    ) is inputs
    assert calls == []
