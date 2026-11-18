"""Keys arriving inside the awaited body swap reach exactly the incoming box."""

import asyncio

import pytest

pytest.importorskip("textual")

from textual import events  # noqa: E402
from textual.widgets import Input  # noqa: E402
from yoke_cli.config.onboard_wizard_widgets import SelectionList  # noqa: E402
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


@pytest.mark.parametrize("activation", ["enter", "ctrl+j", "space"])
@pytest.mark.parametrize("destination", ["input", "selection", "unchanged"])
def test_raw_key_before_selected_delivery_reaches_only_incoming_input(
    monkeypatch, activation, destination,
):
    app, _spy = make_app()

    async def scenario():
        async with app.run_test() as pilot:
            def selected(_value):
                if destination == "input":
                    _input(app)
                elif destination == "selection":
                    app._goto(_View(prompt))

            prompt = SetupPrompt(
                key="test.selection", step=STEP_PROJECT, title="Choose",
                choices=(SelectionRow("only", "Only", ""),),
            )
            app._goto(_View(prompt, on_select=selected))
            await app._apply_pending_swap()
            listing = app.query_one(SelectionList)
            post = listing.post_message
            held = []
            activated = asyncio.Event()

            def hold_selected(message):
                if isinstance(message, SelectionList.Selected):
                    held.append(message)
                    activated.set()
                    return True
                return post(message)

            monkeypatch.setattr(listing, "post_message", hold_selected)
            app.post_message(events.Key(activation, " " if activation == "space" else None))
            await asyncio.wait_for(activated.wait(), 5)
            # The real app queue receives the next key while Selected is held
            # on the old widget, before either body-swap flag can be set.
            assert not app._swap_pending and not app._body_swap_active
            app.post_message(events.Key("slash", "/"))
            processed = asyncio.Event()
            app.call_later(processed.set)
            await asyncio.wait_for(processed.wait(), 5)
            assert app._transition_text == "/"
            for message in held:
                post(message)
            await pilot.pause()
            assert not app._selection_pending
            assert app._transition_text == ""
            if destination == "input":
                field = app.query_one("#onboard-input", Input)
                assert field.value == "/"
                assert field.has_focus
                await pilot.press("z")
                assert field.value == "/z"
            else:
                _input(app)
                await app._apply_pending_swap()
                assert app.query_one("#onboard-input", Input).value == ""

    asyncio.run(scenario())
