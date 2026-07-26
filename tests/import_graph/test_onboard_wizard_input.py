"""Input handling regressions for the Textual onboarding wizard."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("textual")

from rich.text import Text
from textual.widgets import Input, Static

from yoke_cli.config.onboard_terminal import screen_compat_terminal
from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config.onboard_wizard import WizardDefaults
from yoke_cli.config.onboard_wizard_app import OnboardWizardApp
from yoke_cli.config.onboard_wizard_widgets import STEP_PROJECT


def test_first_tilde_reaches_new_input_after_view_swap() -> None:
    asyncio.run(_assert_first_tilde_reaches_new_input())


def test_plain_glyph_body_accepts_input_focus_handoff() -> None:
    asyncio.run(_assert_plain_glyph_body_accepts_input_focus_handoff())


@pytest.mark.parametrize("character", ["\r", "\n", "\t", "\x1b", "\x7f"])
def test_control_keys_never_enter_input_handoff(character: str) -> None:
    app = OnboardWizardApp(
        defaults=WizardDefaults(),
        apply_report=lambda _kwargs: {},
    )

    def unexpected_active_input() -> Input | None:
        raise AssertionError("control keys must not inspect or mutate active input")

    app._active_input = unexpected_active_input  # type: ignore[method-assign]
    app.on_key(SimpleNamespace(character=character))


def test_screen_term_uses_static_divider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TERM", "screen-256color")
    monkeypatch.delenv("STY", raising=False)
    app = OnboardWizardApp(
        defaults=WizardDefaults(),
        apply_report=lambda _kwargs: {},
    )

    assert screen_compat_terminal()
    assert isinstance(app._divider(), Static)


def test_finish_review_states_its_safety_copy_once_at_the_top() -> None:
    """The longest review has to fit its terminal, so it draws one heading.

    An earlier draft repeated the title and subtitle above the Apply rows; that
    second copy pushed the tallest plan past the viewport and scrolled the real
    heading off the top, which is the opposite of what repeating it was for.
    """
    widgets = steps.finish_body(_write_plan_with_many_review_lines())
    texts = _static_texts(widgets)
    review_title = Text.from_markup(steps.REVIEW_TITLE).plain

    assert texts.count(review_title) == 1
    assert texts.count(steps.REVIEW_SUBTITLE) == 1
    assert texts[0] == review_title
    assert texts[1] == steps.REVIEW_SUBTITLE


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


async def _assert_plain_glyph_body_accepts_input_focus_handoff() -> None:
    captured: list[str] = []
    app = OnboardWizardApp(
        defaults=WizardDefaults(),
        apply_report=lambda _kwargs: {},
    )
    app._plain_glyphs = True
    async with app.run_test() as pilot:
        app._goto_input(
            STEP_PROJECT,
            "Clone a project from GitHub.",
            "Paste the public repo's git URL.",
            placeholder="https://github.com/acme/project.git",
            on_done=captured.append,
        )
        await pilot.pause()
        app.set_focus(None)
        await pilot.press("h")
        await pilot.pause()

        widget = app.query_one("#onboard-input", Input)
        assert widget.value == "h"
        assert widget.has_focus

        app.set_focus(None)
        app._refocus_body()
        assert widget.has_focus


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
