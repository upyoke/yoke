"""Every wizard step body scrolls: keys, the wheel, and the scrollbar all reach it.

A step taller than the window used to draw a scrollbar nothing could move: the
wheel and the bar were dead on Apple Terminal because mouse reporting was off
there, and the keys had no route to the non-focusable body. The body is now one
scroll container on every terminal; these gates pin the keyboard route and the
mouse-reporting decision.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from textual.containers import VerticalScroll  # noqa: E402

from runtime.api.cli.onboard_wizard_golden_support import (  # noqa: E402
    FINISH_PLAN_FULL,
    golden_color_env,
    make_app,
)
from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    stub_path_doctor,
    stub_source_branch,
)
from yoke_cli.config.onboard_wizard import WizardDefaults, run_wizard  # noqa: E402
from yoke_cli.config.onboard_terminal import plain_glyphs  # noqa: E402
from yoke_cli.config.onboard_wizard_app import OnboardWizardApp  # noqa: E402
from yoke_cli.config.onboard_wizard_widgets import SelectionList  # noqa: E402

# Wide enough for the rail, short enough that the full Review overflows.
SHORT_TERMINAL = (100, 18)


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    stub_path_doctor(monkeypatch)
    stub_source_branch(monkeypatch)


def _review_app() -> OnboardWizardApp:
    return make_app(apply_report=lambda _kw: FINISH_PLAN_FULL)


async def _open_review(app: OnboardWizardApp, pilot) -> VerticalScroll:
    await pilot.pause()
    await app.workers.wait_for_complete()
    app._goto_finish()
    await app.workers.wait_for_complete()
    await pilot.pause()
    await pilot.pause()
    body = app.query_one("#onboard-body", VerticalScroll)
    assert body.virtual_size.height > body.container_size.height, (
        "the Review screen must overflow for this gate to mean anything"
    )
    return body


def test_page_keys_scroll_the_body_while_a_list_holds_focus() -> None:
    app = _review_app()

    async def scenario() -> None:
        async with app.run_test(size=SHORT_TERMINAL) as pilot:
            body = await _open_review(app, pilot)
            assert isinstance(app.focused, SelectionList)
            body.scroll_home(animate=False)
            await pilot.pause()
            await pilot.press("pagedown")
            await pilot.pause()
            assert body.scroll_y > 0
            await pilot.press("home")
            await pilot.pause()
            assert body.scroll_y == 0
            await pilot.press("end")
            await pilot.pause()
            assert body.scroll_y == body.max_scroll_y

    with golden_color_env():
        asyncio.run(scenario())


def test_arrow_keys_scroll_the_body_when_nothing_is_focused() -> None:
    app = _review_app()

    async def scenario() -> None:
        async with app.run_test(size=SHORT_TERMINAL) as pilot:
            body = await _open_review(app, pilot)
            body.scroll_home(animate=False)
            app.set_focus(None)
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()
            assert body.scroll_y == 1
            await pilot.press("up")
            await pilot.pause()
            assert body.scroll_y == 0

    with golden_color_env():
        asyncio.run(scenario())


def test_footer_hints_stay_docked_below_a_scrolled_body() -> None:
    app = _review_app()

    async def scenario() -> None:
        async with app.run_test(size=SHORT_TERMINAL) as pilot:
            body = await _open_review(app, pilot)
            await pilot.press("end")
            await pilot.pause()
            footer = app.query_one("#onboard-footer")
            assert footer.region.y == SHORT_TERMINAL[1] - 2
            assert body.region.bottom <= footer.region.y

    with golden_color_env():
        asyncio.run(scenario())


def test_the_wheel_route_scrolls_the_same_container() -> None:
    # The wheel lands on whichever child is under the pointer and bubbles to
    # the body; scrolling for the pointer is the handler the wheel calls.
    app = _review_app()

    async def scenario() -> None:
        async with app.run_test(size=SHORT_TERMINAL) as pilot:
            body = await _open_review(app, pilot)
            body.scroll_home(animate=False)
            await pilot.pause()
            assert body.allow_vertical_scroll
            assert body._scroll_down_for_pointer(animate=False)
            await pilot.pause()
            assert body.scroll_y > 0

    with golden_color_env():
        asyncio.run(scenario())


def test_plain_glyph_terminal_keeps_a_scrolling_body_without_scrollbar_glyphs(
    monkeypatch,
) -> None:
    monkeypatch.setenv("YOKE_ONBOARD_FORCE_PLAIN", "1")
    monkeypatch.setenv("TERM", "dumb")
    assert plain_glyphs()
    # Built outside the golden colour env, which would force rich glyphs on.
    app = OnboardWizardApp(
        defaults=WizardDefaults(
            config_path="/tmp/cfg.json", env_name="prod",
            api_url="https://yoke.example.test", token="actor-token",
        ),
        apply_report=lambda _kw: FINISH_PLAN_FULL,
    )
    app.animation_level = "none"

    async def scenario() -> None:
        async with app.run_test(size=SHORT_TERMINAL) as pilot:
            body = await _open_review(app, pilot)
            assert app.screen.has_class("plain-glyphs")
            assert body.styles.scrollbar_size_vertical == 0
            await pilot.press("pagedown")
            await pilot.pause()
            assert body.scroll_y > 0

    asyncio.run(scenario())


@pytest.mark.parametrize("term_program", ["Apple_Terminal", "iTerm.app"])
def test_mouse_reporting_stays_on_in_every_terminal(monkeypatch, term_program) -> None:
    calls: list[dict] = []
    monkeypatch.setenv("TERM_PROGRAM", term_program)
    monkeypatch.setattr(
        OnboardWizardApp, "_hydrate_stored_credentials", lambda *_args: None,
    )
    monkeypatch.setattr(
        OnboardWizardApp, "run", lambda _self, **kwargs: calls.append(kwargs),
    )

    run_wizard(defaults=WizardDefaults(), apply_report=lambda **_kwargs: None)

    assert calls == [{}]
