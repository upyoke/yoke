# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from functools import partial

import asyncio

import pytest

pytest.importorskip("textual")

from yoke_contracts import github_origin  # noqa: E402

from yoke_cli.config import hosted_machine_browser

from yoke_cli.config import github_publish  # noqa: E402

from yoke_cli.config import machine_config  # noqa: E402

from yoke_cli.config import onboard_machine_github  # noqa: E402

from yoke_cli.config import onboard_project  # noqa: E402

from yoke_cli.config import onboard_wizard_flow  # noqa: E402

from yoke_cli.config import onboard_wizard_flow_github  # noqa: E402

from yoke_cli.config import onboard_wizard_flow_publish as publish_flow  # noqa: E402

from yoke_cli.config import onboard_wizard_project_screens as screens  # noqa: E402

from yoke_cli.config import onboard_wizard_steps as steps  # noqa: E402

from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    accept_project_details,
    advance_past_path,
    make_app,
    skip_hosting,
    stub_path_doctor,
    type_text,
)


@pytest.fixture(autouse=True)
def _stubs(monkeypatch):
    stub_path_doctor(monkeypatch)
    monkeypatch.setattr(
        onboard_wizard_flow,
        "fetch_repo_owners",
        lambda _api_url, _token: [github_publish.RepoOwner("octocat", "user")],
    )
    monkeypatch.setattr(
        publish_flow,
        "user_access_token",
        lambda _result: "short-lived-publish-access",
    )


def _github_config(
    *,
    administration: bool,
    suspended: bool = False,
    repository_selection: str = "all",
) -> dict:
    permissions = {"administration": "write"} if administration else {}
    return {
        "installations": [
            {
                "installation_id": 7,
                "account_login": "octocat",
                "permissions": permissions,
                "suspended": suspended,
                "repository_selection": repository_selection,
            }
        ]
    }


def _body_text(app) -> str:
    from textual.widgets import Static

    return " ".join(
        str(widget.render())
        for widget in app.query("#onboard-body Static").results(Static)
    )


def _mark_connected(app) -> None:
    app.result.machine_github_choice = onboard_machine_github.CHOICE_CONNECT
    app.result.machine_github_verification = {"ok": True, "ready": True}
    app.result.machine_github_api_url = github_origin.DEFAULT_GITHUB_API_URL
