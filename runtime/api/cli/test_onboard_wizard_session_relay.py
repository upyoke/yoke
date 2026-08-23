"""Review and Setup-complete teaching for the explicit relay install."""

from __future__ import annotations

import sys

from yoke_cli.config import onboard_session_relay
from yoke_cli.config.onboard_wizard_apply_steps import apply_success_body
from yoke_cli.config.onboard_wizard_plan_review import classify_plan


def _text(widgets) -> str:
    return "\n".join(str(widget.render()) for widget in widgets)


def test_review_lists_plist_login_item_and_existing_token(monkeypatch) -> None:
    monkeypatch.setattr(onboard_session_relay.sys, "platform", "darwin")
    steps = onboard_session_relay.plan_steps(local_destination=False)

    grouped = classify_plan({"plan": {"steps": steps}})

    assert grouped["machine"] == [
        "Install the machine relay plist at "
        "~/Library/LaunchAgents/com.upyoke.relay[.<environment-id>].plist",
        "Load the machine relay as a login item",
        "Reuse this machine's existing Yoke API token",
    ]


def test_setup_complete_repeats_all_three_relay_facts() -> None:
    rendered = _text(apply_success_body(None, relay_installed=True))

    for line in onboard_session_relay.RELAY_SETUP_COMPLETE_LINES:
        assert line in rendered


def test_apply_bridge_runs_packaged_installer_without_credentials(monkeypatch) -> None:
    monkeypatch.setattr(onboard_session_relay.sys, "platform", "darwin")
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return type("Result", (), {"returncode": 0})()

    assert onboard_session_relay.install(
        local_destination=False,
        runner=runner,
    )
    command, kwargs = calls[0]
    assert command == [
        sys.executable,
        "-m",
        "yoke_core.tools.install_session_relay",
        "install",
    ]
    assert kwargs["capture_output"] is True
    assert not any("token" in part.lower() for part in command)
