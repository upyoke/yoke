"""Onboard GitHub completion matches `yoke github status` ready."""

from __future__ import annotations

from types import SimpleNamespace

from yoke_cli.config import github_machine_report
from yoke_cli.config import onboard_machine_github
from yoke_cli.config import onboard_wizard_github_state as github_state
from yoke_cli.config.onboard_wizard_widgets import (
    STEP_GITHUB,
    STEP_PROJECT,
    stepper_mark,
)


def _result(**fields: object) -> SimpleNamespace:
    return SimpleNamespace(
        machine_github_choice=onboard_machine_github.CHOICE_CONNECT,
        **fields,
    )


def test_github_rail_stays_pending_after_later_steps_without_ready() -> None:
    assert (
        stepper_mark(
            STEP_GITHUB,
            active=STEP_PROJECT,
            github_complete=False,
        )
        == "pending"
    )


def test_github_rail_is_done_on_later_steps_only_when_ready() -> None:
    assert (
        stepper_mark(
            STEP_GITHUB,
            active=STEP_PROJECT,
            github_complete=True,
        )
        == "done"
    )


def test_github_rail_is_active_on_the_github_step_even_when_not_ready() -> None:
    assert (
        stepper_mark(
            STEP_GITHUB,
            active=STEP_GITHUB,
            github_complete=False,
        )
        == "active"
    )


def test_connected_matches_status_ready_on_a_not_configured_report() -> None:
    report = github_machine_report.not_configured(None, None)

    assert report["configured"] is False
    assert report["ready"] is False
    assert github_state.ready_from_report(report) is False
    assert github_state.connected(_result(machine_github_verification=report)) is False


def test_connected_matches_status_ready_on_a_stub_ready_report() -> None:
    ready = {"ok": True, "ready": True, "configured": True}
    not_ready = {"ok": True, "ready": False, "configured": True}

    assert github_state.connected(_result(machine_github_verification=ready)) is True
    assert (
        github_state.connected(
            _result(machine_github_verification=not_ready),
        )
        is False
    )


def test_connected_rejects_configured_false_even_if_ready_is_set() -> None:
    report = {"ok": True, "ready": True, "configured": False}

    assert github_state.connected(_result(machine_github_verification=report)) is False


def test_skip_is_not_connected_even_with_a_ready_report() -> None:
    result = SimpleNamespace(
        machine_github_choice=onboard_machine_github.CHOICE_SKIP,
        machine_github_verification={"ok": True, "ready": True, "configured": True},
    )

    assert github_state.connected(result) is False
