"""Visibility-choice routing for clone onboarding."""

from __future__ import annotations

from typing import Any

from yoke_cli.config import github_publish
from yoke_cli.config import onboard_wizard_project_screens as project_screens


def fetch_private_repos(
    api_url: str, token: str, *, web_url: str,
) -> list:
    """List private repositories for the wizard's picker."""

    return github_publish.list_user_repos(
        api_url, token, private_only=True, web_url=web_url,
    )


def route_visibility(shell: Any, choice: str) -> None:
    """Record whether a clone needs machine auth and route to its input."""

    if choice == project_screens.CLONE_VISIBILITY_PRIVATE:
        shell.result.project_clone_requires_machine_github = True
        shell._goto_private_repo_picker()
        return
    shell.result.project_clone_requires_machine_github = False
    shell._goto_clone_url_input()


__all__ = ["fetch_private_repos", "route_visibility"]
