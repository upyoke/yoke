"""Review, Setup-complete, and convergence for the explicit relay install."""

from __future__ import annotations

import subprocess
import sys

import pytest

from yoke_cli.config import onboard_session_relay
from yoke_cli.config.onboard_wizard_apply_steps import apply_success_body
from yoke_cli.config.onboard_wizard_plan_review import classify_plan


def _text(widgets) -> str:
    return "\n".join(str(widget.render()) for widget in widgets)


def _result(returncode: int, *, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _recording_runner(*results):
    """A runner that returns each queued result and records its calls."""
    calls: list[list[str]] = []
    queued = list(results)

    def runner(command, **kwargs):
        calls.append(list(command))
        outcome = queued.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    return runner, calls


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


def test_setup_complete_says_a_satisfied_relay_was_left_running() -> None:
    fragment = {
        "planned": True,
        "installed": True,
        "local_build": False,
        "reused": True,
    }

    rendered = _text(
        apply_success_body(
            None,
            relay_lines=onboard_session_relay.report_complete_lines(fragment),
        )
    )

    assert "already installed and current" in rendered
    assert "left it running" in rendered


def test_setup_complete_stays_silent_when_no_relay_was_installed() -> None:
    fragment = {"planned": True, "installed": False, "local_build": True}

    assert onboard_session_relay.report_complete_lines(fragment) == ()


@pytest.mark.parametrize("local_destination", (False, True))
def test_apply_bridge_runs_packaged_installer_without_credentials(
    monkeypatch, local_destination: bool
) -> None:
    monkeypatch.setattr(onboard_session_relay.sys, "platform", "darwin")
    runner, calls = _recording_runner(_result(1), _result(0))

    outcome = onboard_session_relay.install(
        local_destination=local_destination,
        environment="upyoke",
        config_path="/tmp/machine-config.json",
        runner=runner,
    )

    assert outcome == onboard_session_relay.RelayInstallOutcome(
        installed=True, reused=False
    )
    status_command, install_command = calls
    assert status_command == [
        sys.executable,
        "-m",
        "yoke_core.tools.install_session_relay",
        "status",
        "--environment",
        "upyoke",
        "--config",
        "/tmp/machine-config.json",
    ]
    assert install_command[4:] == status_command[4:]
    assert install_command[3] == "install"
    assert not any("token" in part.lower() for part in install_command)


def test_a_satisfied_relay_is_reused_and_never_reinstalled(monkeypatch) -> None:
    """The on-screen retry must not unload the login item it just installed."""
    monkeypatch.setattr(onboard_session_relay.sys, "platform", "darwin")
    runner, calls = _recording_runner(_result(0))

    outcome = onboard_session_relay.install(
        local_destination=False, environment="upyoke", runner=runner
    )

    assert outcome == onboard_session_relay.RelayInstallOutcome(
        installed=True, reused=True
    )
    assert [command[3] for command in calls] == ["status"]


def test_an_unreadable_status_repairs_rather_than_skipping(monkeypatch) -> None:
    monkeypatch.setattr(onboard_session_relay.sys, "platform", "darwin")
    runner, calls = _recording_runner(
        subprocess.TimeoutExpired(cmd="status", timeout=1), _result(0)
    )

    outcome = onboard_session_relay.install(
        local_destination=False, environment="upyoke", runner=runner
    )

    assert outcome.installed and not outcome.reused
    assert [command[3] for command in calls] == ["status", "install"]


def test_a_failed_install_reports_the_installer_diagnosis(monkeypatch) -> None:
    monkeypatch.setattr(onboard_session_relay.sys, "platform", "darwin")
    runner, _calls = _recording_runner(
        _result(1),
        _result(
            2,
            stderr=(
                "session relay: relay_release_fetch_failed: could not fetch "
                "yoke-core==0.1.1 from https://api.upyoke.com/simple/"
            ),
        ),
    )

    with pytest.raises(onboard_session_relay.OnboardSessionRelayError) as raised:
        onboard_session_relay.install(
            local_destination=False, environment="upyoke", runner=runner
        )

    message = str(raised.value)
    assert "installer exit 2" in message
    assert "relay_release_fetch_failed" in message
    assert "could not fetch yoke-core==0.1.1" in message
    assert "yoke --env upyoke relay status" in message
    assert "yoke --env upyoke relay install" in message


def test_installer_detail_redacts_credentials_and_bounds_length() -> None:
    noise = "filler line\n" * 400
    detail = onboard_session_relay.installer_detail(
        _result(
            1,
            stdout=noise,
            stderr=(
                "Authorization: Bearer sk-secret-value\n"
                "index https://user:hunter2@api.upyoke.com/simple/ refused\n"
                "token=sk-another-secret\n"
            ),
        )
    )

    assert "sk-secret-value" not in detail
    assert "hunter2" not in detail
    assert "sk-another-secret" not in detail
    assert len(detail) <= onboard_session_relay.RELAY_DETAIL_MAX_CHARS


def test_a_timeout_names_the_budget_it_exceeded(monkeypatch) -> None:
    monkeypatch.setattr(onboard_session_relay.sys, "platform", "darwin")
    runner, _calls = _recording_runner(
        _result(1),
        subprocess.TimeoutExpired(cmd="install", timeout=1),
    )

    with pytest.raises(onboard_session_relay.OnboardSessionRelayError) as raised:
        onboard_session_relay.install(
            local_destination=False, environment="upyoke", runner=runner
        )

    message = str(raised.value)
    assert str(onboard_session_relay.RELAY_INSTALL_TIMEOUT_SECONDS) in message
    assert "did not finish" in message


def test_apply_records_what_the_relay_step_did(monkeypatch) -> None:
    monkeypatch.setattr(onboard_session_relay.sys, "platform", "darwin")
    monkeypatch.setattr(
        onboard_session_relay,
        "install",
        lambda **kwargs: onboard_session_relay.RelayInstallOutcome(
            installed=True, reused=True
        ),
    )
    report: dict = {}
    emitted: list[tuple[str, str, str]] = []

    onboard_session_relay.apply(
        lambda action, target, status: emitted.append((action, target, status)),
        report,
        local_destination=False,
        config_path="/tmp/machine-config.json",
        environment="upyoke",
    )

    assert report["session_relay"] == {
        "planned": True,
        "installed": True,
        "plist": onboard_session_relay.RELAY_PLIST_TARGET,
        "local_build": False,
        "reused": True,
    }
    assert {status for _action, _target, status in emitted} == {"running", "done"}


def test_relay_is_unsupported_off_darwin_for_every_destination(monkeypatch) -> None:
    """launchd is the supervisor, so the platform decides -- not the plane."""
    monkeypatch.setattr(onboard_session_relay.sys, "platform", "linux")

    for local_destination in (False, True):
        assert not onboard_session_relay.is_supported(
            local_destination=local_destination
        )
        assert (
            onboard_session_relay.plan_steps(local_destination=local_destination) == []
        )
        assert not onboard_session_relay.install(
            local_destination=local_destination
        ).installed
