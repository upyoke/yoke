"""Remote copy leaves app mode, preserves the view, and uses local selection."""

from __future__ import annotations

import asyncio
import base64
from contextlib import contextmanager

import pytest
from textual.app import SuspendNotSupported
from textual.drivers.headless_driver import HeadlessDriver
from textual.widgets import Input

from runtime.api.cli.onboard_wizard_test_helpers import make_app, stub_path_doctor
from runtime.api.cli.test_onboard_wizard_copy_and_open import CODE, LONG_URL, _Shell
from yoke_cli.config import onboard_clipboard
from yoke_cli.config import onboard_wizard_copy_open as copy_open
from yoke_cli.config.onboard_wizard_state import CopyTarget


@pytest.mark.parametrize(
    ("platform", "env", "remote"),
    [
        ("darwin", {}, False),
        ("win32", {}, False),
        ("darwin", {"SSH_CONNECTION": "client server"}, True),
        ("linux", {"SSH_TTY": "/dev/pts/0", "DISPLAY": ":0"}, True),
        ("linux", {}, True),
        ("linux", {"DISPLAY": ":0"}, False),
        ("linux", {"WAYLAND_DISPLAY": "wayland-0"}, False),
    ],
)
def test_remote_detection(platform, env, remote):
    assert onboard_clipboard.remote_session(env, platform=platform) is remote


@pytest.mark.parametrize("value", [CODE, LONG_URL, "café/☀"])
def test_terminal_clipboard_sequence_is_exact_utf8(value):
    encoded = base64.b64encode(value.encode("utf-8")).decode("ascii")
    assert onboard_clipboard.osc52(value) == f"\x1b]52;c;{encoded}\x07"


@pytest.mark.parametrize("action", ["action_copy_target", "action_open_target"])
def test_remote_keys_suspend_before_printing_and_resume(monkeypatch, capsys, action):
    monkeypatch.setattr(onboard_clipboard, "remote_session", lambda: True)
    monkeypatch.setattr(
        onboard_clipboard, "copy", lambda _: pytest.fail("remote clipboard")
    )
    monkeypatch.setattr(copy_open, "open_url", lambda _: pytest.fail("remote browser"))
    shell = _Shell()
    target = CopyTarget("the approval link", LONG_URL, is_url=True)
    shell._set_copy_targets([target])
    events = []

    @contextmanager
    def suspend():
        events.append("suspended")
        try:
            yield
        finally:
            events.append("resumed")

    def enter():
        assert events == ["suspended"]
        assert capsys.readouterr().out == (
            onboard_clipboard.osc52(LONG_URL)
            + LONG_URL
            + "\n"
            + copy_open.COPY_RETURN_PROMPT
            + "\n"
        )
        events.append("enter")
        return ""

    monkeypatch.setattr(shell, "suspend", suspend, raising=False)
    monkeypatch.setattr("builtins.input", enter)
    assert "show the approval link to copy" in shell.footer.rendered[-1]
    getattr(shell, action)()
    assert events == ["suspended", "enter", "resumed"]
    assert shell._copy_targets == (target,)
    assert "Shown the approval link" in shell.footer.rendered[-1]


@pytest.mark.parametrize("failure", [EOFError, OSError, KeyboardInterrupt])
def test_interrupted_terminal_input_resumes_without_advancing(monkeypatch, failure):
    monkeypatch.setattr(onboard_clipboard, "remote_session", lambda: True)
    shell = _Shell()
    shell._set_copy_targets([CopyTarget("code", CODE)])
    resumed = []

    @contextmanager
    def suspend():
        yield
        resumed.append(True)

    def interrupt():
        raise failure()

    monkeypatch.setattr(shell, "suspend", suspend, raising=False)
    monkeypatch.setattr("builtins.input", interrupt)
    shell.action_copy_target()
    assert resumed == [True]
    assert shell._copy_cursor == 0
    assert "terminal_copy_interrupted" in shell.footer.rendered[-1]
    assert "retry Ctrl-Y" in shell.footer.rendered[-1]


def test_unsupported_suspend_teaches_terminal_recovery(monkeypatch):
    monkeypatch.setattr(onboard_clipboard, "remote_session", lambda: True)
    shell = _Shell()
    shell._set_copy_targets([CopyTarget("code", CODE)])

    @contextmanager
    def suspend():
        raise SuspendNotSupported()
        yield

    monkeypatch.setattr(shell, "suspend", suspend, raising=False)
    shell.action_copy_target()
    assert "terminal_copy_suspend_unavailable" in shell.footer.rendered[-1]
    assert shell._copy_cursor == 0


def test_copy_chord_preserves_actual_wizard_screen_focus_and_input(monkeypatch):
    stub_path_doctor(monkeypatch)
    monkeypatch.setattr(onboard_clipboard, "remote_session", lambda: True)
    # Exercise App.suspend itself with a driver that permits terminal handoff.
    monkeypatch.setattr(HeadlessDriver, "can_suspend", property(lambda _: True))
    app, _ = make_app()
    events = []

    async def scenario():
        async with app.run_test() as pilot:
            await pilot.pause()
            field = Input("keep this typed value", id="copy-test-input")
            await app.screen.mount(field)
            field.focus()
            app._set_copy_targets(
                [
                    CopyTarget("code", CODE),
                    CopyTarget("link", LONG_URL, is_url=True),
                ]
            )
            screen, result = app.screen, app.result
            monkeypatch.setattr(
                app._driver,
                "suspend_application_mode",
                lambda: events.append("suspend"),
            )
            monkeypatch.setattr(
                app._driver, "resume_application_mode", lambda: events.append("resume")
            )

            def enter():
                assert events[-1] == "suspend"
                assert app.screen is screen
                return ""

            monkeypatch.setattr("builtins.input", enter)
            await pilot.press("ctrl+y")
            await pilot.pause()
            assert events == ["suspend", "resume"]
            assert app.screen is screen
            assert app.result is result
            assert app.focused is field
            assert field.value == "keep this typed value"
            assert app._current_copy_target().value == LONG_URL
            await pilot.press("ctrl+o")
            await pilot.pause()
            assert events == ["suspend", "resume", "suspend", "resume"]
            assert app.focused is field

    asyncio.run(scenario())
