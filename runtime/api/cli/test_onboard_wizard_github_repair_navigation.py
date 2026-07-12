"""GitHub installation repair and project-access navigation safety."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("textual")

from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    advance_past_path,
    stub_path_doctor,
)
from runtime.api.cli.test_onboard_wizard_github_navigation_safety import (  # noqa: E402
    _app,
    _body_text,
    _row_values,
    _stored_revoked_config,
)
from yoke_cli.config import onboard_wizard_flow_clone  # noqa: E402
from yoke_cli.config import onboard_wizard_flow_clone_source  # noqa: E402
from yoke_cli.config import onboard_wizard_flow_github as github_flow  # noqa: E402
from yoke_cli.config import onboard_wizard_flow_publish  # noqa: E402
from yoke_cli.config import onboard_wizard_flow_publish_manual  # noqa: E402
from yoke_cli.config import onboard_wizard_project_github  # noqa: E402
from yoke_cli.config import onboard_wizard_steps as steps  # noqa: E402


@pytest.fixture(autouse=True)
def _offline_path(monkeypatch):
    stub_path_doctor(monkeypatch)


def test_review_copy_names_already_saved_machine_github() -> None:
    widgets = steps.finish_body(
        {
            "plan": {
                "steps": [
                    {"action": "set-active-env", "target": "prod"},
                ]
            }
        },
        machine_github_saved=True,
    )
    text = " ".join(str(widget.render()) for widget in widgets)
    assert "Machine GitHub authorization is already saved" in text
    assert "only the remaining setup writes wait for Apply" in text
    assert "yoke github disconnect" in text
    assert "Nothing is written until you choose Apply" not in text


def _installation_repair_report(*, suspended: bool = False) -> dict:
    settings_url = "https://github.com/settings/installations/123"
    code = (
        "github_app_installation_suspended"
        if suspended
        else "github_app_installation_permissions_incomplete"
    )
    return {
        "ok": False,
        "configured": True,
        "ready": False,
        "api_url": "https://api.github.com",
        "authorization": {"present": True, "status": "authorized"},
        "access": {"installations": [{"installation_id": 123}]},
        "permissions": {
            "items": [
                {
                    "installation_id": 123,
                    "account_login": "octo-org",
                    "suspended": suspended,
                    "evaluation": {"ok": False},
                    "settings_url": settings_url,
                }
            ]
        },
        "issues": [
            {"severity": "warning", "code": code, "message": "repair it"},
            {
                "severity": "error",
                "code": "github_app_no_usable_installation",
                "message": "no usable installation",
            },
        ],
    }


def test_permission_repair_check_reaches_project_without_reconnecting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, _credential = _stored_revoked_config(tmp_path)
    ready = {
        "ok": True,
        "configured": True,
        "ready": True,
        "api_url": "https://api.github.com",
        "authorization": {"present": True, "status": "authorized"},
        "permissions": {"usable": True, "items": []},
        "issues": [],
    }
    reports = iter([_installation_repair_report(), ready])
    calls: list[str] = []
    monkeypatch.setattr(
        github_flow.github_machine,
        "status",
        lambda **kwargs: calls.append("status") or next(reports),
    )
    monkeypatch.setattr(
        github_flow.github_machine,
        "connect",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("permission repair must not restart OAuth")
        ),
    )
    app = _app(config)

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "GitHub App access needs repair" in _body_text(app)
            assert "https://github.com/settings/installations/123" in _body_text(app)
            repair_depth = len(app._history)
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert len(app._history) == repair_depth
            assert "GitHub connected." in _body_text(app)
            assert _row_values(app) == ["continue"]
            await pilot.press("enter")
            await pilot.pause()
            assert _row_values(app) == [row.value for row in steps.MODE_ROWS]

    asyncio.run(scenario())
    assert calls == ["status", "status"]


def test_suspended_installation_remains_repairable_with_bounded_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, _credential = _stored_revoked_config(tmp_path)
    report = _installation_repair_report(suspended=True)
    monkeypatch.setattr(
        github_flow.github_machine,
        "status",
        lambda **kwargs: report,
    )
    app = _app(config)

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            repair_depth = len(app._history)
            assert "GitHub App access needs repair" in _body_text(app)
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert len(app._history) == repair_depth
            await pilot.press("down", "down")
            await pilot.press("enter")
            await pilot.pause()
            assert len(app._history) == repair_depth - 1

    asyncio.run(scenario())


def test_project_access_refresh_not_ready_keeps_one_picker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app(tmp_path / "config.json")
    config_state = {
        "api_url": "https://api.github.com",
        "web_url": "https://github.com",
        "app_slug": "yoke-product",
        "installations": [],
        "repositories": [],
    }
    monkeypatch.setattr(
        onboard_wizard_project_github.machine_config,
        "github_config",
        lambda _path=None: config_state,
    )
    monkeypatch.setattr(
        onboard_wizard_project_github.github_machine,
        "status",
        lambda **kwargs: {"ok": True, "ready": False},
    )

    async def scenario() -> None:
        async with app.run_test() as pilot:
            app.result.project_github_repo = "octo-org/private"
            app._goto_project_github_access()
            await pilot.pause()
            picker_depth = len(app._history)
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert len(app._history) == picker_depth
            assert _row_values(app) == [
                row.value for row in steps.PROJECT_GITHUB_ACCESS_ROWS
            ]
            await pilot.press("down", "down")
            await pilot.press("enter")
            await pilot.pause()
            assert len(app._history) == picker_depth - 1

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", [False, RuntimeError("browser unavailable")])
def test_project_access_browser_failure_renders_copyable_settings_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: object,
) -> None:
    app = _app(tmp_path / "config.json")
    settings_url = (
        "https://github.com/organizations/octo-org/settings/installations/123"
    )
    config_state = {
        "api_url": "https://api.github.com",
        "web_url": "https://github.com",
        "app_slug": "yoke-product",
        "installations": [
            {
                "installation_id": 123,
                "account_login": "octo-org",
                "html_url": settings_url,
            }
        ],
        "repositories": [],
    }
    monkeypatch.setattr(
        onboard_wizard_project_github.machine_config,
        "github_config",
        lambda _path=None: config_state,
    )

    def open_browser(url: str) -> bool:
        if isinstance(failure, BaseException):
            raise failure
        return bool(failure)

    monkeypatch.setattr(
        onboard_wizard_project_github.webbrowser,
        "open",
        open_browser,
    )
    captured = {"body": ""}

    async def scenario() -> None:
        async with app.run_test() as pilot:
            app.result.project_github_repo = "octo-org/private"
            app._open_project_github_access()
            app._goto_project_github_access()
            await pilot.pause()
            captured["body"] = _body_text(app)

    asyncio.run(scenario())

    assert "browser did not open" in captured["body"]
    assert settings_url in captured["body"]


def test_every_github_token_check_blocks_quit_until_worker_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict] = []

    class _CaptureShell:
        result = SimpleNamespace(
            api_url="https://api.test",
            config_path="/tmp/config.json",
            machine_github_api_url="https://api.github.com",
            machine_github_choice="connect",
            machine_github_verification={"ok": True, "ready": True},
            project_remote_url="https://github.com/acme/widgets.git",
            project_github_repo="acme/widgets",
        )

        def _run_checking(self, **kwargs) -> None:
            calls.append(kwargs)

        def __getattr__(self, _name):
            return lambda *_args, **_kwargs: None

    shell = _CaptureShell()
    monkeypatch.setattr(
        onboard_wizard_flow_clone,
        "github_connected",
        lambda _result: True,
    )
    monkeypatch.setattr(
        onboard_wizard_flow_clone.project_screens,
        "default_repo",
        lambda *_args, **_kwargs: "acme/widgets",
    )

    onboard_wizard_flow_clone.CloneFlow._goto_private_repo_picker(shell)
    onboard_wizard_flow_clone_source.CloneSourceFlow._after_remote(
        shell,
        "https://github.com/acme/widgets.git",
    )
    onboard_wizard_flow_clone.CloneFlow._goto_clone_outcome(shell)
    onboard_wizard_flow_publish.PublishFlow._goto_owner_picker(shell)
    onboard_wizard_flow_publish_manual.ManualPublishFlow._check_manual_publish_repositories(
        shell,
        replace_current=False,
    )
    onboard_wizard_project_github.ProjectGithubAccessFlow._on_project_github_access(
        shell,
        "refresh",
    )

    assert [call["group"] for call in calls] == [
        "onboard-private-repos",
        "onboard-clone-source",
        "onboard-source-access",
        "onboard-owner-picker",
        "onboard-manual-publish-repositories",
        "onboard-project-github-access",
    ]
    assert all(call.get("blocks_quit") is True for call in calls)
