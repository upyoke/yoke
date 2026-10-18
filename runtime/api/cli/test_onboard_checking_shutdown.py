"""Checking results must not route views after the wizard stops."""

import asyncio

import pytest

pytest.importorskip("textual")

from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    advance_past_path,
    make_app,
    stub_path_doctor,
)


@pytest.fixture
def app(monkeypatch):
    stub_path_doctor(monkeypatch)
    wizard, _spy = make_app()
    return wizard


@pytest.mark.parametrize("error", [None, RuntimeError("probe failed")])
def test_stopped_app_discards_completion_before_rendering(app, error):
    async def scenario():
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            assert app.is_running
        assert not app.is_running
        assert not list(app.query("#onboard-body"))
        history = list(app._history)
        app._checking = True
        app._checking_blocks_quit = True
        app._checking_token += 1
        cancel = app._checking_cancel = lambda: pytest.fail("check cancelled")

        def render(_result):
            app._render_current()

        app._finish_checking(app._checking_token, render, render, None, error)
        assert app._history == history
        assert app._checking
        assert app._checking_blocks_quit
        assert app._checking_cancel is cancel

    asyncio.run(scenario())


@pytest.mark.parametrize("error", [None, RuntimeError("probe failed")])
@pytest.mark.parametrize("state", ["live", "stale", "cancelled"])
def test_running_completion_preserves_token_and_cancel_contract(app, error, state):
    async def scenario():
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            history = list(app._history)
            app._history.append(object())
            app._checking = True
            app._checking_blocks_quit = True
            app._checking_token += 1
            token = app._checking_token
            calls = []
            app._checking_cancel = lambda: calls.append(("cancel", None))
            if state == "stale":
                app._checking_token += 1
            elif state == "cancelled":
                assert app._cancel_checking()
            before = (
                list(app._history),
                app._checking,
                app._checking_blocks_quit,
                app._checking_cancel,
                app._checking_token,
            )
            app._finish_checking(
                token,
                lambda value: calls.append(("success", value)),
                lambda value: calls.append(("error", value)),
                "result",
                error,
            )
            if state == "live":
                assert calls == [
                    ("success", "result") if error is None else ("error", error)
                ]
                assert app._history == history
                assert not app._checking
                assert not app._checking_blocks_quit
                assert app._checking_cancel is None
                assert app._checking_token == token
            else:
                assert calls == ([("cancel", None)] if state == "cancelled" else [])
                assert (
                    list(app._history),
                    app._checking,
                    app._checking_blocks_quit,
                    app._checking_cancel,
                    app._checking_token,
                ) == before

    asyncio.run(scenario())
