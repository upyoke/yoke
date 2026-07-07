"""Input handling regressions for the Textual onboarding wizard."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from rich.text import Text
from textual.widgets import Input, Static

from yoke_cli.config.onboard_terminal import screen_compat_terminal
from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config.onboard_wizard import WizardDefaults
from yoke_cli.config.onboard_wizard_app import OnboardWizardApp
from yoke_cli.config.onboard_wizard_widgets import STEP_PROJECT, SelectionList


def test_first_tilde_reaches_new_input_after_view_swap() -> None:
    asyncio.run(_assert_first_tilde_reaches_new_input())


def test_screen_term_uses_static_divider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TERM", "screen-256color")
    monkeypatch.delenv("STY", raising=False)
    app = OnboardWizardApp(
        defaults=WizardDefaults(),
        apply_report=lambda _kwargs: {},
    )

    assert screen_compat_terminal()
    assert isinstance(app._divider(), Static)


def test_finish_review_repeats_safety_copy_next_to_apply_rows() -> None:
    widgets = steps.finish_body(_write_plan_with_many_review_lines())
    texts = _static_texts(widgets)
    review_title = Text.from_markup(steps.REVIEW_TITLE).plain

    assert texts.count(review_title) == 2
    assert texts.count(steps.REVIEW_SUBTITLE) == 2

    confirm_index = next(
        index for index, widget in enumerate(widgets)
        if isinstance(widget, SelectionList)
    )
    nearby_texts = _static_texts(widgets[confirm_index - 4:confirm_index])
    assert review_title in nearby_texts
    assert steps.REVIEW_SUBTITLE in nearby_texts


async def _assert_first_tilde_reaches_new_input() -> None:
    captured: list[str] = []
    app = OnboardWizardApp(
        defaults=WizardDefaults(),
        apply_report=lambda _kwargs: {},
    )
    async with app.run_test() as pilot:
        app._goto_input(
            STEP_PROJECT,
            "Point at your project folder.",
            "Where's the code on this machine?",
            placeholder="~/code/my-project",
            on_done=captured.append,
        )
        await pilot.press("~")
        await pilot.pause()

        widget = app.query_one("#onboard-input", Input)
        assert widget.value == "~"


def _static_texts(widgets: list[object]) -> list[str]:
    return [str(widget.render()) for widget in widgets if isinstance(widget, Static)]


def _write_plan_with_many_review_lines() -> dict[str, object]:
    return {
        "plan": {
            "project": {"name": "My Project"},
            "steps": [
                {"action": "set-active-env", "target": "stage"},
                {"action": "set-https-api-url", "target": "https://api.stage.upyoke.com"},
                {"action": "store-token-reference", "target": "~/.yoke/secrets/token"},
                {"action": "machine-github-connection", "target": "GitHub"},
                {"action": "create-runtime-dir", "target": "~/.yoke/tmp"},
                {"action": "project-checkout-register", "target": "/tmp/my-project"},
                {"action": "project-source-choice", "target": "existing folder"},
                {"action": "project-github-auth-choice", "target": "store token"},
                {"action": "project-onboard", "target": "my-project"},
                {"action": "project-create-checkout", "target": "/tmp/my-project"},
                {"action": "project-install-scaffold", "target": ".yoke/"},
                {"action": "project-write-board-art", "target": "BOARD.md"},
            ],
        }
    }


__all__ = []
