"""Setup hands agent callers public data and paints TUI notice before opening."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from yoke_cli.config import github_device_flow, github_machine_access
from yoke_cli.config import hosted_machine_authorization, setup_browser
from yoke_cli.config.hosted_machine_browser import BrowserOpenResult
from runtime.api.cli.test_github_app_device_flow import _Response
from yoke_cli.commands.adapters import onboard_hosted_authorization as hosted_setup


def test_agent_device_flow_never_opens_native_browser(monkeypatch):
    monkeypatch.setattr(
        setup_browser, "open_url", lambda *a, **k: pytest.fail("agent browser opened")
    )
    payloads = iter(
        [
            {
                "device_code": "private-device",
                "user_code": "ABCD-EFGH",
                "verification_uri": "https://github.com/login/device",
                "expires_in": 900,
                "interval": 5,
            },
            {
                "access_token": "private-token",
                "expires_in": 28800,
                "refresh_token": "private-refresh",
                "refresh_token_expires_in": 15552000,
            },
        ]
    )
    events = []
    result = github_device_flow.authorize(
        client_id="Iv1.local",
        web_url="https://github.com",
        opener=lambda req, timeout: _Response(next(payloads), req.full_url),
        notify=events.append,
        sleep=lambda _: None,
        monotonic=lambda: 0,
    )
    assert not result.browser_opened
    assert events[0]["browser_action"]["user_code"] == "ABCD-EFGH"
    assert events[0]["browser_action"]["instructions"]
    assert events[1]["browser_attempted"] is False
    assert "private-" not in json.dumps(events)
    assert "ABCD-EFGH" not in json.dumps(
        github_machine_access.report_safe_progress_event(events[0])
    )


def test_agent_machine_sign_in_preserves_complete_prefilled_url(monkeypatch):
    pending = SimpleNamespace(
        verification_uri_complete="https://app.upyoke.com/connect?user_code=K7F2"
    )
    monkeypatch.setattr(hosted_machine_authorization, "start", lambda *a, **k: pending)
    monkeypatch.setattr(
        hosted_machine_authorization, "complete", lambda *a, **k: "approved"
    )
    monkeypatch.setattr(
        setup_browser, "open_url", lambda *a, **k: pytest.fail("agent browser opened")
    )
    events = []
    assert (
        hosted_machine_authorization.authorize(
            "https://app.upyoke.com",
            notify=lambda p, browser: events.append((p, browser)),
        )
        == "approved"
    )
    assert events[0][0].verification_uri_complete.endswith("user_code=K7F2")
    assert events[0][1].attempted is False


def test_agent_app_installation_returns_instructions_without_opening(monkeypatch):
    monkeypatch.setattr(
        setup_browser, "open_url", lambda *a, **k: pytest.fail("agent browser opened")
    )
    report = {"install_url": "https://github.com/apps/example/installations/new"}
    events = []
    github_machine_access.open_install_page(
        report, browser_open=None, notify=events.append, pending=True
    )
    assert report["state"] == "pending_installation"
    assert report["browser_action"]["url"] == report["install_url"]
    assert events[-1]["browser_attempted"] is False


def test_tui_notice_and_copy_targets_exist_before_opener(monkeypatch):
    calls = []
    shell = SimpleNamespace(
        _run_checking=lambda **kwargs: calls.append(kwargs),
        call_from_thread=lambda fn, *args: fn(*args),
        call_after_refresh=lambda callback: callback(),
    )
    monkeypatch.setattr(setup_browser, "open_url", lambda url: BrowserOpenResult(True))
    outcomes = []
    setup_browser.open_in_wizard(
        shell,
        "https://github.com/settings/installations/123",
        step="project",
        on_success=outcomes.append,
    )
    view = calls[0]
    assert view["title"] == "Opening your browser…"
    assert view["copy_targets"][0].value.endswith("/123")
    assert not outcomes
    view["on_success"](view["work"]())
    assert outcomes[0].opened
    view["on_error"](OSError("browser unavailable"))
    assert "copy the link" in outcomes[1].reason


def test_agent_progress_is_flushed_json_and_has_no_false_open_failure(capsys):
    setup_browser.render_progress(
        {
            "phase": "device_authorization",
            "browser_action": setup_browser.action(
                "https://github.com/login/device",
                "Enter the code and approve.",
                user_code="ABCD-EFGH",
            ),
        },
        json_mode=True,
    )
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["browser_action"]["user_code"] == "ABCD-EFGH"
    assert "did not open" not in output.err


def test_agent_setup_reuses_saved_browser_approved_reference(tmp_path, monkeypatch):
    token_file = tmp_path / "approved.token"
    token_file.write_text("synthetic-test-token")
    monkeypatch.setattr(
        hosted_setup.machine_config,
        "active_connection",
        lambda *a, **k: {
            "transport": "https",
            "api_url": "https://app.upyoke.com/api/orgs/acme",
            "env": "acme",
            "credential_source": {"kind": "token_file", "path": str(token_file)},
        },
    )
    parsed = SimpleNamespace(
        config_path=None,
        env_name=None,
        api_url="https://app.upyoke.com",
        token=None,
        token_file=None,
        token_stdin=False,
    )
    assert hosted_setup.hydrate_saved(parsed, "hosted")
    assert parsed.token_file == str(token_file)
    assert parsed.env_name == "acme"
    assert not hosted_setup.usage_error("hosted", False, True, False)
