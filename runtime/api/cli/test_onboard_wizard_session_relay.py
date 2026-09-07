"""Review and Setup-complete teaching for the explicit relay install."""

from __future__ import annotations

import sys

import pytest

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


def test_review_plans_the_relay_for_a_local_destination(monkeypatch) -> None:
    """A local install plans a relay too; only its build source differs."""
    monkeypatch.setattr(onboard_session_relay.sys, "platform", "darwin")
    steps = onboard_session_relay.plan_steps(local_destination=True)

    actions = [step["action"] for step in steps]

    assert actions[:2] == [
        "install-session-relay-plist",
        "load-session-relay-login-item",
    ]
    assert actions[2] == "run-session-relay-on-installed-yoke"
    # A local universe has no account and no API token to reuse.
    assert not any("token" in action for action in actions)


def test_setup_complete_repeats_all_relay_facts() -> None:
    fragment = {"planned": True, "installed": True, "local_build": False}
    rendered = _text(
        apply_success_body(
            None,
            relay_lines=onboard_session_relay.report_complete_lines(fragment),
        )
    )

    for line in onboard_session_relay.setup_complete_lines(local_destination=False):
        assert line in rendered


def test_setup_complete_names_the_local_relay_build_source() -> None:
    fragment = {"planned": True, "installed": True, "local_build": True}
    rendered = _text(
        apply_success_body(
            None,
            relay_lines=onboard_session_relay.report_complete_lines(fragment),
        )
    )

    assert "installed Yoke" in rendered
    assert "no" in rendered and "API token" in rendered
    # The served-release wording belongs to the https destinations only.
    assert "release served by its selected environment" not in rendered


def test_setup_complete_stays_silent_when_no_relay_was_installed() -> None:
    fragment = {"planned": True, "installed": False, "local_build": True}

    assert onboard_session_relay.report_complete_lines(fragment) == ()


@pytest.mark.parametrize("local_destination", (False, True))
def test_apply_bridge_runs_packaged_installer_without_credentials(
    monkeypatch, local_destination: bool
) -> None:
    monkeypatch.setattr(onboard_session_relay.sys, "platform", "darwin")
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return type("Result", (), {"returncode": 0})()

    assert onboard_session_relay.install(
        local_destination=local_destination,
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
    assert kwargs["timeout"] == onboard_session_relay.RELAY_INSTALL_TIMEOUT_SECONDS
    assert not any("token" in part.lower() for part in command)


def test_relay_is_unsupported_off_darwin_for_every_destination(monkeypatch) -> None:
    """launchd is the supervisor, so the platform decides -- not the plane."""
    monkeypatch.setattr(onboard_session_relay.sys, "platform", "linux")

    for local_destination in (False, True):
        assert not onboard_session_relay.is_supported(
            local_destination=local_destination
        )
        assert onboard_session_relay.plan_steps(local_destination=local_destination) == []
