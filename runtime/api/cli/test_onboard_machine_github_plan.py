"""Dry-run truthfulness for the machine GitHub App connection step."""

from pathlib import Path

import pytest

from yoke_cli.config import onboard_machine_github


def test_connect_plan_reports_machine_secret_mutation() -> None:
    report = onboard_machine_github.plan(
        choice=onboard_machine_github.CHOICE_CONNECT,
        api_url=None,
    )

    assert report["applied"] is False
    assert report["requires_browser_flow"] is True
    assert report["writes_machine_secret"] is True


def test_non_connect_plans_report_no_machine_secret_mutation() -> None:
    for choice in (
        onboard_machine_github.CHOICE_SKIP,
        onboard_machine_github.CHOICE_LATER,
    ):
        report = onboard_machine_github.plan(choice=choice, api_url=None)

        assert report["requires_browser_flow"] is False
        assert report["writes_machine_secret"] is False


def test_apply_rejects_existing_connection_on_different_requested_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        onboard_machine_github.machine_config,
        "github_config",
        lambda path: {"api_url": "https://api.github.com"},
    )
    monkeypatch.setattr(
        onboard_machine_github.github_machine,
        "status",
        lambda **kwargs: pytest.fail(
            "origin mismatch must fail before checking the existing connection"
        ),
    )

    with pytest.raises(
        onboard_machine_github.OnboardMachineGithubError,
        match="different API origin",
    ):
        onboard_machine_github.apply(
            choice=onboard_machine_github.CHOICE_CONNECT,
            config_path=Path("/tmp/config.json"),
            api_url="https://github.example/api/v3",
        )
