"""GitHub binding for detected origins in existing project checkouts."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    advance_past_path,
    complete_board_art,
    make_app,
    stub_path_doctor,
    type_text,
)
from runtime.api.cli.test_yoke_operations_cli_onboard_wizard_existing_project import (  # noqa: E402
    _body_text,
    _configure_origin,
)
from yoke_cli.config import existing_project_lookup  # noqa: E402
from yoke_cli.config import machine_config  # noqa: E402
from yoke_cli.config import onboard_local_checkout_identity  # noqa: E402
from yoke_cli.config import onboard_machine_github  # noqa: E402
from yoke_cli.config import onboard_wizard_flow_publish  # noqa: E402


@pytest.fixture(autouse=True)
def _stub_path_doctor(monkeypatch):
    stub_path_doctor(monkeypatch)


def test_existing_backlog_project_can_bind_detected_checkout_origin(
    tmp_path,
    monkeypatch,
) -> None:
    checkout = tmp_path / "legacy"
    (checkout / ".yoke").mkdir(parents=True)
    (checkout / ".yoke" / "install-manifest.json").write_text(
        '{"manifest_schema": 1, "project_id": 37}\n',
        encoding="utf-8",
    )
    _configure_origin(checkout, "example-org/legacy")
    monkeypatch.setattr(
        existing_project_lookup,
        "find_by_project_id",
        lambda **_: existing_project_lookup.ExistingProject(
            id=37,
            slug="legacy",
            name="Legacy",
            github_repo="",
            default_branch="main",
            public_item_prefix="LEG",
            github_sync_mode="backlog_only",
        ),
    )

    def detect_origin(result, _value):
        result.project_github_repo = "example-org/legacy"
        result.project_source_default_branch = "main"
        return "https://github.com/example-org/legacy.git", "https://github.com"

    monkeypatch.setattr(
        onboard_local_checkout_identity,
        "inspect",
        detect_origin,
    )
    monkeypatch.setattr(
        machine_config,
        "github_config",
        lambda _path: {
            "installations": [
                {
                    "installation_id": 7,
                    "account_login": "example-org",
                    "repository_selection": "selected",
                    "permissions": {"contents": "write"},
                }
            ],
            "repositories": [
                {
                    "repository_id": 9,
                    "installation_id": 7,
                    "full_name": "example-org/legacy",
                }
            ],
        },
    )
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("enter")  # connect GitHub
            await app.workers.wait_for_complete()
            await pilot.press("enter")  # existing folder
            await type_text(pilot, str(checkout))
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "Existing Yoke project found." in _body_text(app)
            await pilot.press("enter")  # continue to GitHub adoption
            await pilot.pause()
            assert "How should Yoke manage this project on GitHub?" in _body_text(app)
            await pilot.press("enter")  # use connected installation
            await pilot.pause()
            assert "repository access found" in _body_text(app)
            await pilot.press("enter")
            await complete_board_art(pilot)
            await pilot.press("enter")
            await pilot.pause()

    asyncio.run(scenario())

    applied = spy.applied
    assert applied is not None
    assert applied["existing_project_id"] == 37
    assert applied["project_github_repo"] == "example-org/legacy"
    assert applied["project_github_adoption"] == "app-binding"
    assert applied["project_github_adoption_preserve"] is False
    assert applied["machine_github_choice"] == onboard_machine_github.CHOICE_CONNECT


def test_new_project_keeps_existing_origin_and_reaches_binding(
    tmp_path,
    monkeypatch,
) -> None:
    checkout = tmp_path / "new-project"
    checkout.mkdir()
    _configure_origin(checkout, "example-org/new-project")

    def detect_origin(result, _value):
        result.project_github_repo = "example-org/new-project"
        result.project_source_default_branch = "trunk"
        return (
            "https://github.com/example-org/new-project.git",
            "https://github.com",
        )

    monkeypatch.setattr(
        onboard_local_checkout_identity,
        "inspect",
        detect_origin,
    )
    monkeypatch.setattr(
        onboard_wizard_flow_publish,
        "has_remote",
        lambda _path: True,
    )
    monkeypatch.setattr(
        machine_config,
        "github_config",
        lambda _path: {
            "installations": [
                {
                    "installation_id": 7,
                    "account_login": "example-org",
                    "repository_selection": "selected",
                    "permissions": {"contents": "write"},
                }
            ],
            "repositories": [
                {
                    "repository_id": 9,
                    "installation_id": 7,
                    "full_name": "example-org/new-project",
                }
            ],
        },
    )
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("enter")  # connect GitHub
            await app.workers.wait_for_complete()
            await pilot.press("enter")  # existing folder
            await type_text(pilot, str(checkout))
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.press("enter")  # accept slug
            await pilot.press("enter")  # accept name; keep remote auto-routes
            await pilot.press("enter")  # accept prefix
            await pilot.pause()
            assert "How should Yoke manage this project on GitHub?" in _body_text(app)
            await pilot.press("enter")
            await pilot.press("enter")
            await complete_board_art(pilot)
            await pilot.press("enter")
            await pilot.pause()

    asyncio.run(scenario())

    applied = spy.applied
    assert applied is not None
    assert applied["existing_project_id"] is None
    assert applied["project_keep_existing_remote"] is True
    assert applied["project_github_repo"] == "example-org/new-project"
    assert applied["project_default_branch"] == "trunk"
    assert applied["project_github_adoption"] == "app-binding"
    assert applied["project_github_adoption_preserve"] is False
