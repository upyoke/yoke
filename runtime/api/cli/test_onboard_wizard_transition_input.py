"""Keys arriving inside the awaited body swap reach exactly the incoming box."""

import asyncio

import pytest

pytest.importorskip("textual")

from textual import events  # noqa: E402
from textual.widgets import Input  # noqa: E402
from yoke_cli.config.onboard_wizard_state import _View  # noqa: E402
from yoke_cli.config.onboard_wizard_step_ids import STEP_PROJECT  # noqa: E402
from yoke_cli.config.setup_prompt import SelectionRow, SetupPrompt  # noqa: E402
from runtime.api.cli.onboard_wizard_test_helpers import make_app  # noqa: E402


def _input(app):
    app._goto_input(
        "test.path", STEP_PROJECT, "Path", "Enter a path",
        placeholder="", on_done=lambda _value: None,
    )


@pytest.mark.parametrize("leading", ["/", "~"])
def test_keys_survive_pending_unmount_and_mount_without_duplication(monkeypatch, leading):
    app, _spy = make_app()

    async def scenario():
        async with app.run_test() as pilot:
            body = app.query_one("#onboard-body")
            remove = body.remove_children
            mount = body.mount

            async def remove_with_keys():
                assert app._pending_input is None
                await app.on_event(events.Key("a", "a"))
                await remove()
                await app.on_event(events.Key("b", "b"))

            async def mount_with_keys(*widgets, **kwargs):
                await app.on_event(events.Key("c", "c"))
                await mount(*widgets, **kwargs)
                await app.on_event(events.Key("d", "d"))

            monkeypatch.setattr(body, "remove_children", remove_with_keys)
            monkeypatch.setattr(body, "mount", mount_with_keys)
            _input(app)
            await app.on_event(events.Key("slash" if leading == "/" else "tilde", leading))
            await app._apply_pending_swap()
            field = app.query_one("#onboard-input", Input)
            assert field.value == leading + "abcd"
            assert app.focused is field
            await pilot.press("z")
            assert field.value == leading + "abcdz"
            assert app._transition_text == ""

    asyncio.run(scenario())


def test_transition_keys_for_a_selection_do_not_leak_to_a_later_input():
    app, _spy = make_app()

    async def scenario():
        async with app.run_test():
            app._goto(_View(SetupPrompt(
                key="test.selection", step=STEP_PROJECT, title="Choose",
                choices=(SelectionRow("only", "Only", ""),),
            )))
            await app.on_event(events.Key("x", "x"))
            await app._apply_pending_swap()
            assert app._transition_text == ""
            _input(app)
            await app._apply_pending_swap()
            field = app.query_one("#onboard-input", Input)
            assert field.value == ""

    asyncio.run(scenario())
