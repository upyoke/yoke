"""Shared deterministic seams for onboarding clone-flow pilots."""

from __future__ import annotations

from typing import Any

from yoke_cli.config import github_publish
from yoke_cli.config import onboard_wizard_flow
from yoke_cli.config import onboard_wizard_flow_clone as clone_flow
from yoke_cli.config import onboard_wizard_steps as steps

from runtime.api.cli.onboard_wizard_github_app_test_support import (
    stub_github_app_access,
)
from runtime.api.cli.onboard_wizard_test_helpers import (
    stub_path_doctor,
    stub_source_branch,
)


def configure_clone_flow(monkeypatch: Any) -> None:
    """Keep clone pilots offline with one deterministic App topology."""

    stub_path_doctor(monkeypatch)
    stub_source_branch(monkeypatch, "main")
    monkeypatch.setattr(
        onboard_wizard_flow,
        "fetch_repo_owners",
        lambda api_url, token: [
            github_publish.RepoOwner("octocat", "user"),
            github_publish.RepoOwner("acme-inc", "organization"),
        ],
    )
    stub_github_app_access(
        monkeypatch,
        owners=("octocat", "acme-inc", "acme", "example-org"),
        repositories=(
            "acme/widgets",
            "octocat/widgets",
            "example-org/buzz",
        ),
        user_access_token="short-lived-clone-access",
    )
    monkeypatch.setattr(
        clone_flow.CloneFlow, "_source_push_access", lambda self: None
    )


async def pick_mode(pilot: Any, value: str) -> None:
    """Select one project mode by its stable row value."""

    index = next(i for i, row in enumerate(steps.MODE_ROWS) if row.value == value)
    for _ in range(index):
        await pilot.press("down")
    await pilot.press("enter")


__all__ = ["configure_clone_flow", "pick_mode"]
