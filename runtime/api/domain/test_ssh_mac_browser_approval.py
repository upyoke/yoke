"""Native Safari approval is exact-target, visible-control automation."""

from __future__ import annotations

import subprocess

import pytest

from yoke_core.domain.ssh_mac_browser_approval import approve_machine_in_safari


def _completed(
    command: str,
    *,
    stdout: str = "",
    returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, returncode, stdout, "")


def test_approval_targets_the_exact_code_tab_and_visible_button() -> None:
    commands: list[str] = []

    def run(command: str, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return _completed(
            command,
            stdout="approved|https://app.stage.upyoke.com/orgs/acme#/overview\n",
        )

    result = approve_machine_in_safari(
        run,
        verification_url="https://app.stage.upyoke.com/connect",
        user_code="AB12-CD34",
    )

    assert result.ok is True
    assert result.error_code is None
    assert result.evidence == {
        "approval_entry": "/connect",
        "browser": "Safari",
        "result_url": "https://app.stage.upyoke.com/orgs/acme",
        "visible_control": "Approve machine",
    }
    assert len(commands) == 1
    assert "https://app.stage.upyoke.com/connect?user_code=AB12-CD34" in commands[0]
    assert "Approve machine" in commands[0]
    assert 'perform action "AXPress"' in commands[0]
    assert 'return "approved|" & resultURL' in commands[0]


@pytest.mark.parametrize(
    ("verification_url", "user_code"),
    (
        ("http://app.stage.upyoke.com/connect", "AB12-CD34"),
        ("https://app.stage.upyoke.com/anything", "AB12-CD34"),
        ("https://app.stage.upyoke.com/connect?other=1", "AB12-CD34"),
        ("https://app.stage.upyoke.com/connect", "bad-code"),
    ),
)
def test_invalid_context_never_reaches_safari(
    verification_url: str,
    user_code: str,
) -> None:
    commands: list[str] = []

    result = approve_machine_in_safari(
        lambda command, **_kwargs: commands.append(command) or _completed(command),
        verification_url=verification_url,
        user_code=user_code,
    )

    assert result.ok is False
    assert result.error_code == "machine_browser_context_invalid"
    assert commands == []


@pytest.mark.parametrize(
    ("stdout", "error_code"),
    (
        ("browser_tab_missing\n", "machine_browser_tab_missing"),
        (
            "approval_control_missing\n",
            "machine_browser_approval_control_missing",
        ),
        (
            "approval_navigation_missing\n",
            "machine_browser_approval_navigation_missing",
        ),
        (
            "approved|https://evil.example/orgs/acme\n",
            "machine_browser_approval_destination_invalid",
        ),
        (
            "approved|https://app.stage.upyoke.com/connect?status=denied\n",
            "machine_browser_approval_destination_invalid",
        ),
    ),
)
def test_automation_refuses_missing_or_untrusted_browser_outcomes(
    stdout: str,
    error_code: str,
) -> None:
    result = approve_machine_in_safari(
        lambda command, **_kwargs: _completed(command, stdout=stdout),
        verification_url="https://app.stage.upyoke.com/connect",
        user_code="AB12-CD34",
    )

    assert result.ok is False
    assert result.error_code == error_code
