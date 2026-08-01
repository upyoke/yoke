"""Native transcript-selection behavior for the onboarding wizard."""

from __future__ import annotations

import pytest

from yoke_cli.config.onboard_terminal import native_text_selection_terminal
from yoke_cli.config.onboard_wizard import WizardDefaults, run_wizard
from yoke_cli.config.onboard_wizard_app import OnboardWizardApp


def test_native_text_selection_is_limited_to_apple_terminal() -> None:
    assert native_text_selection_terminal({"TERM_PROGRAM": "Apple_Terminal"})
    assert not native_text_selection_terminal({"TERM_PROGRAM": "iTerm.app"})
    assert not native_text_selection_terminal({})


def test_apple_terminal_disables_textual_mouse_reporting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bool] = []
    monkeypatch.setenv("TERM_PROGRAM", "Apple_Terminal")
    monkeypatch.setattr(
        OnboardWizardApp,
        "_hydrate_stored_credentials",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        OnboardWizardApp,
        "run",
        lambda _self, *, mouse: calls.append(mouse),
    )

    run_wizard(
        defaults=WizardDefaults(),
        apply_report=lambda **_kwargs: None,
    )

    assert calls == [False]


def test_regular_terminal_preserves_textual_mouse_reporting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bool] = []
    monkeypatch.setenv("TERM_PROGRAM", "iTerm.app")
    monkeypatch.setattr(
        OnboardWizardApp,
        "_hydrate_stored_credentials",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        OnboardWizardApp,
        "run",
        lambda _self, *, mouse: calls.append(mouse),
    )

    run_wizard(
        defaults=WizardDefaults(),
        apply_report=lambda **_kwargs: None,
    )

    assert calls == [True]
