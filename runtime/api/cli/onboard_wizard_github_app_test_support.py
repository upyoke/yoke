"""Deterministic GitHub App setup for onboarding wizard flow tests."""

from __future__ import annotations

from typing import Any, Iterable

from yoke_cli.config import machine_config
from yoke_cli.config import onboard_wizard_flow_github as github_flow
from yoke_cli.config import onboard_wizard_flow_publish as publish_flow
from yoke_cli.config import onboard_wizard_github_state as github_state
from yoke_cli.config import onboard_wizard_steps as steps

from runtime.api.cli.onboard_wizard_test_helpers import advance_past_path


def stub_github_app_access(
    monkeypatch: Any,
    *,
    owners: Iterable[str],
    repositories: Iterable[str],
    user_access_token: str,
) -> None:
    """Expose App config only after the browser connection completes."""
    connected = False
    stubbed_connect = github_flow.github_machine.connect
    owner_list = tuple(owners)
    repository_list = tuple(repositories)
    installation_ids = {
        owner.casefold(): index for index, owner in enumerate(owner_list, start=1)
    }

    def _connect(**kwargs: Any) -> dict[str, Any]:
        nonlocal connected
        connected = True
        return stubbed_connect(**kwargs)

    def _github_config(_path: Any) -> dict[str, Any]:
        if not connected:
            return {}
        return {
            "api_url": "https://api.github.com",
            "web_url": "https://github.com",
            "installations": [
                {
                    "installation_id": index,
                    "account_login": owner,
                    "permissions": {"administration": "write"},
                    "suspended": False,
                }
                for index, owner in enumerate(owner_list, start=1)
            ],
            "repositories": [
                {
                    "full_name": repository,
                    "installation_id": installation_ids.get(
                        repository.split("/", 1)[0].casefold(),
                        1,
                    ),
                }
                for repository in repository_list
            ],
        }

    def _user_access_token(result: Any) -> str | None:
        return user_access_token if github_state.connected(result) else None

    monkeypatch.setattr(github_flow.github_machine, "connect", _connect)
    monkeypatch.setattr(machine_config, "github_config", _github_config)
    monkeypatch.setattr(github_state, "user_access_token", _user_access_token)
    monkeypatch.setattr(publish_flow, "user_access_token", _user_access_token)


async def connect_github_app(app: Any, pilot: Any) -> None:
    """Complete the stubbed browser flow and wait for project-mode routing."""
    await advance_past_path(pilot)
    await pilot.press("enter")
    await app.workers.wait_for_complete()
    await pilot.pause()


async def select_connected_repository(app: Any, pilot: Any) -> None:
    """Choose App binding and acknowledge exact-repository access."""
    index = next(
        index
        for index, row in enumerate(steps.PROJECT_GITHUB_ROWS)
        if row.value == "reuse-machine"
    )
    for _ in range(index):
        await pilot.press("down")
    await pilot.press("enter")
    await pilot.pause()
    assert app.result.project_github_adoption == "app-binding", (
        app.result.project_github_repo,
        machine_config.github_config(app.result.config_path),
    )
    await pilot.press("enter")
    await pilot.pause()


__all__ = [
    "connect_github_app",
    "select_connected_repository",
    "stub_github_app_access",
]
