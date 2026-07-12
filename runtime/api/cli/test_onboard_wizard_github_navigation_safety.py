"""Real Textual pilots for GitHub choice, retry, and Back safety."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

pytest.importorskip("textual")

from yoke_cli.config import onboard_wizard_flow_github as github_flow  # noqa: E402
from yoke_cli.config import onboard_machine_github  # noqa: E402
from yoke_cli.config import onboard_wizard_steps as steps  # noqa: E402
from yoke_cli.config.onboard_wizard import WizardDefaults  # noqa: E402
from yoke_cli.config.onboard_wizard_widgets import SelectionList  # noqa: E402
from textual.widgets import Static  # noqa: E402

from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    advance_past_path,
    make_app,
    stub_path_doctor,
)


@pytest.fixture(autouse=True)
def _offline_path(monkeypatch):
    stub_path_doctor(monkeypatch)


def _stored_revoked_config(tmp_path: Path) -> tuple[Path, Path]:
    credential = tmp_path / "github-app-user-legacy.json"
    credential.write_bytes(b"legacy-refresh-document\n")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({
        "schema_version": 1,
        "github": {
            "client_id": "Iv1.product",
            "app_slug": "yoke-product",
            "app_id": 123,
            "api_url": "https://api.github.com",
            "web_url": "https://github.com",
            "authorization": {
                "kind": "github_app_user_authorization",
                "refresh_credential_ref": str(credential),
                "status": "revoked",
            },
        },
    }), encoding="utf-8")
    return config, credential


def _app(config: Path):
    return make_app(WizardDefaults(
        config_path=str(config),
        env_name="prod",
        api_url="https://api.test",
        token="actor-token",
    ))[0]


def _row_values(app) -> list[str]:
    selection = app.query_one("#onboard-body SelectionList", SelectionList)
    return [row.value for row in selection.rows]


def _body_text(app) -> str:
    return " ".join(
        str(widget.render())
        for widget in app.query("#onboard-body Static").results(Static)
    )


def test_stored_revoked_backlog_is_zero_network_and_zero_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, credential = _stored_revoked_config(tmp_path)
    before = config.read_bytes(), credential.read_bytes()
    calls: list[str] = []
    monkeypatch.setattr(
        github_flow.github_machine,
        "status",
        lambda **kwargs: calls.append("status"),
    )
    monkeypatch.setattr(
        github_flow.github_machine,
        "connect",
        lambda **kwargs: calls.append("connect"),
    )
    app = _app(config)

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            assert _row_values(app) == [row.value for row in steps.MACHINE_GITHUB_ROWS]
            await pilot.press("down")
            await pilot.press("enter")
            await pilot.pause()

    asyncio.run(scenario())

    assert app.result.machine_github_choice == "skip"
    assert calls == []
    assert (config.read_bytes(), credential.read_bytes()) == before


def test_backlog_choice_clears_run_scoped_connected_state() -> None:
    class Shell(github_flow.MachineGithubFlow):
        result = type("Result", (), {
            "machine_github_choice": onboard_machine_github.CHOICE_CONNECT,
            "machine_github_verification": {"ok": True, "ready": True},
            "machine_github_api_url": "https://api.github.com",
        })()
        advanced = False

        def _goto_project_mode(self) -> None:
            self.advanced = True

    shell = Shell()
    shell._on_machine_github(onboard_machine_github.CHOICE_SKIP)

    assert shell.advanced is True
    assert shell.result.machine_github_choice == onboard_machine_github.CHOICE_SKIP
    assert shell.result.machine_github_verification is None
    assert shell.result.machine_github_api_url is None


def test_saved_authorization_retries_live_check_without_new_device_flow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "config.json"
    connect_calls: list[str] = []
    status_calls: list[str] = []
    transient = {
        "ok": False,
        "ready": False,
        "configured": True,
        "authorization": {"present": True, "status": "authorized"},
        "issues": [{
            "code": "github_live_check_failed",
            "message": "GitHub returned HTTP 503",
        }],
    }
    ready = {
        "ok": True,
        "ready": True,
        "configured": True,
        "api_url": "https://api.github.com",
        "authorization": {"present": True, "status": "authorized"},
        "issues": [],
    }
    monkeypatch.setattr(
        github_flow.github_machine,
        "connect",
        lambda **kwargs: connect_calls.append("connect") or transient,
    )
    monkeypatch.setattr(
        github_flow.github_machine,
        "status",
        lambda **kwargs: status_calls.append("status") or ready,
    )
    app = _app(config)

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "without repeating browser authorization" in _body_text(app)
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "GitHub connected." in _body_text(app)

    asyncio.run(scenario())

    assert connect_calls == ["connect"]
    assert status_calls == ["status"]
    assert app.result.machine_github_verification == ready


def test_stored_revoked_back_has_no_browser_and_reconnect_is_explicit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, _credential = _stored_revoked_config(tmp_path)
    calls: list[str] = []
    connect_kwargs: list[dict[str, object]] = []
    failed = {
        "ok": False,
        "ready": False,
        "issues": [{"message": "authorization was revoked"}],
    }
    connected = {
        "ok": True,
        "configured": True,
        "ready": True,
        "api_url": "https://api.github.com",
        "identity": {"login": "octocat"},
        "access": {"owners": [], "repos": []},
        "permissions": {"ok": True, "usable": True},
        "issues": [],
    }
    monkeypatch.setattr(
        github_flow.github_machine,
        "status",
        lambda **kwargs: calls.append("status") or failed,
    )
    monkeypatch.setattr(
        github_flow.github_machine,
        "connect",
        lambda **kwargs: (
            connect_kwargs.append(dict(kwargs)),
            calls.append("connect"),
            connected,
        )[-1],
    )
    app = _app(config)

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert _row_values(app)[0] == "reconnect"
            await pilot.press("down", "down")
            await pilot.press("enter")
            await pilot.pause()
            assert _row_values(app) == [row.value for row in steps.MACHINE_GITHUB_ROWS]
            assert calls == ["status"]
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()

    asyncio.run(scenario())

    assert calls == ["status", "status", "connect"]
    assert len(connect_kwargs) == 1
    assert str(connect_kwargs[0]["config_path"]) == str(config)
    assert connect_kwargs[0]["service_api_url"] == "https://api.test"
    assert connect_kwargs[0]["replace_profile"] is True
    assert callable(connect_kwargs[0]["notify"])


def test_pending_check_still_pending_then_back_does_not_reload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "config.json"
    pending = {
        "ok": True,
        "configured": True,
        "ready": False,
        "state": "pending_installation",
        "api_url": "https://api.github.com",
        "install_url": "https://github.com/apps/yoke-product/installations/new",
        "issues": [],
    }
    calls: list[str] = []
    def connect(**kwargs):
        calls.append("connect")
        config.write_text(json.dumps({
            "schema_version": 1,
            "github": {"authorization": {"status": "authorized"}},
        }), encoding="utf-8")
        return pending

    monkeypatch.setattr(github_flow.github_machine, "connect", connect)
    monkeypatch.setattr(
        github_flow.github_machine,
        "status",
        lambda **kwargs: calls.append("status") or pending,
    )
    app = _app(config)

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.result.machine_github_saved is True
            assert "already saved" in _body_text(app)
            assert "yoke github disconnect" in _body_text(app)
            assert config.is_file()
            pending_depth = len(app._history)
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert len(app._history) == pending_depth
            await pilot.press("down", "down")
            await pilot.press("enter")
            await pilot.pause()
            assert _row_values(app) == [row.value for row in steps.MACHINE_GITHUB_ROWS]

    asyncio.run(scenario())
    assert calls == ["connect", "status"]
