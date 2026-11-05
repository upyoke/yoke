"""Pilot-driven coverage for the wizard's Install + PATH front steps."""

from __future__ import annotations

from runtime.api.cli.yoke_operations_cli_onboard_wizard_path_test_support import (
    _diagnosis as _diagnosis,
)


import asyncio

import pytest

pytest.importorskip("textual")

from textual.widgets import Rule, Static  # noqa: E402
from textual.containers import VerticalScroll  # noqa: E402

from yoke_cli import main as yoke_operations_cli  # noqa: E402
from yoke_cli.config import path_doctor  # noqa: E402
from yoke_cli.config.onboard_terminal import plain_text  # noqa: E402
from yoke_cli.config.onboard_wizard import WizardDefaults  # noqa: E402
from yoke_cli.config.onboard_wizard_app import OnboardWizardApp  # noqa: E402
from yoke_cli.config.onboard_wizard_widgets import (  # noqa: E402
    STEP_INSTALL,
    STEPPER_ORDER,
    Stepper,
)

UNSAFE_SCREEN_GLYPHS = set("☀✓✔✗●○◐⊘›•→▌─│┃━═—–…↵↑↓·")


def _all_clear_diagnosis() -> path_doctor.PathDiagnosis:
    return _diagnosis(needs_fix=False)


@pytest.fixture
def stub_path(monkeypatch):
    """Install a needs-fix diagnosis and a successful immediate repair."""
    monkeypatch.setattr(path_doctor, "diagnose", lambda **_: _diagnosis(needs_fix=True))

    def apply(plan, *, progress, report):
        del progress
        report["path_repair"] = {
            **plan,
            "login_verified": True,
            "login_resolved": {tool: f"/bin/{tool}" for tool in path_doctor.TOOLS},
        }

    monkeypatch.setattr("yoke_cli.config.onboard_apply_path.apply", apply)


def _app(defaults: WizardDefaults | None = None) -> OnboardWizardApp:
    return OnboardWizardApp(
        defaults=defaults
        or WizardDefaults(
            config_path="/tmp/cfg.json",
            env_name="prod",
            api_url="https://api.test",
            token="actor-token",
        ),
        apply_report=lambda kwargs: {"plan": {"steps": []}},
    )


def _visible_static_text(app: OnboardWizardApp) -> str:
    return "\n".join(str(widget.render()) for widget in app.query(Static))


def test_stepper_order_uses_consistent_noun_labels() -> None:
    labels = [label for _id, label in STEPPER_ORDER]
    assert labels == [
        "Install",
        "Account",
        "GitHub",
        "Project",
        "Hosting",
        "Review",
    ]
    assert STEPPER_ORDER[0] == ("install", "Install")
    assert STEPPER_ORDER[1] == ("connect", "Account")
    assert STEPPER_ORDER[-2] == ("hosting", "Hosting")
    assert STEPPER_ORDER[-1] == ("finish", "Review")


def test_plain_text_replaces_screen_unsafe_glyphs() -> None:
    assert plain_text("☀ ✓ ✗ → ─ │ — … ·") == "* OK x -> - | - ... -"


def test_screen_terminal_uses_ascii_visible_glyphs(monkeypatch, stub_path) -> None:
    monkeypatch.setenv("YOKE_ONBOARD_FORCE_PLAIN", "1")
    monkeypatch.setenv("TERM", "screen-256color")
    monkeypatch.setenv("STY", "1234.yoke-test")
    monkeypatch.setattr(
        "yoke_cli.config.onboard_apply_path.apply",
        lambda *a, **k: (_ for _ in ()).throw(OSError("uv_shell_update_failed")),
    )
    app = _app(
        WizardDefaults(
            config_path="/tmp/cfg.json",
            env_name="prod",
            api_url="https://api.test",
            token="actor-token",
            post_install=True,
        )
    )

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.screen.has_class("plain-glyphs")
            body = app.query_one("#onboard-body")
            assert isinstance(body, VerticalScroll)
            text = _visible_static_text(app)
            assert "* Yoke" in text
            assert "up/down navigate" in text
            assert "Retry Install" in text
            assert not (UNSAFE_SCREEN_GLYPHS & set(text))

            app._goto_project_mode()
            await pilot.pause()
            text = _visible_static_text(app)
            assert "Edit Yoke source" in text
            assert not (UNSAFE_SCREEN_GLYPHS & set(text))

    asyncio.run(scenario())


def test_dumb_terminal_uses_ascii_visible_glyphs(monkeypatch, stub_path) -> None:
    monkeypatch.setenv("YOKE_ONBOARD_FORCE_PLAIN", "1")
    monkeypatch.setenv("TERM", "dumb")
    monkeypatch.delenv("STY", raising=False)
    monkeypatch.setattr(
        "yoke_cli.config.onboard_apply_path.apply",
        lambda *a, **k: (_ for _ in ()).throw(OSError("uv_shell_update_failed")),
    )
    app = _app(
        WizardDefaults(
            config_path="/tmp/cfg.json",
            env_name="prod",
            api_url="https://api.test",
            token="actor-token",
            post_install=True,
        )
    )

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.screen.has_class("plain-glyphs")
            assert not app._screen_compat
            assert app._plain_glyphs
            assert list(app.query(Rule)) == []
            text = _visible_static_text(app)
            assert "* Yoke" in text
            assert "up/down navigate" in text
            assert not (UNSAFE_SCREEN_GLYPHS & set(text))

    asyncio.run(scenario())


@pytest.mark.parametrize("post_install", [False, True])
def test_install_runs_without_confirmation_and_has_no_history(stub_path, post_install):
    app = _app(
        WizardDefaults(
            config_path="/tmp/cfg.json",
            env_name="prod",
            api_url="https://api.test",
            token="actor-token",
            post_install=post_install,
        )
    )

    async def scenario():
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.query_one(Stepper).active != STEP_INSTALL
            assert all(view.step != STEP_INSTALL for view in app._history)
            assert app.result.path_repair["login_verified"]

    asyncio.run(scenario())


def test_all_clear_install_does_not_write(monkeypatch):
    monkeypatch.setattr(path_doctor, "diagnose", _all_clear_diagnosis)

    def unexpected(*args, **kwargs):
        pytest.fail("Healthy Install must not run shell repair")

    monkeypatch.setattr("yoke_cli.config.onboard_apply_path.apply", unexpected)
    app = _app()

    async def scenario():
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.query_one(Stepper).active != STEP_INSTALL

    asyncio.run(scenario())


def test_failed_install_stays_on_install_and_retry_advances(monkeypatch):
    monkeypatch.setattr(path_doctor, "diagnose", _all_clear_diagnosis)
    app = _app()

    def fail():
        raise OSError("shell-file permissions")

    monkeypatch.setattr(path_doctor, "diagnose", fail)

    async def scenario():
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.query_one(Stepper).active == STEP_INSTALL
            text = _visible_static_text(app)
            assert "install_check_failed" in text
            assert "shell-file permissions" in text
            assert "Retry Install" in text
            monkeypatch.setattr(path_doctor, "diagnose", _all_clear_diagnosis)
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.query_one(Stepper).active != STEP_INSTALL
            assert all(view.step != STEP_INSTALL for view in app._history)

    asyncio.run(scenario())


def test_onboard_post_install_flag_parses(monkeypatch, capsys) -> None:
    captured: dict = {}

    def fake_run_wizard(defaults, *, apply_report):
        captured["post_install"] = defaults.post_install
        from yoke_cli.config.onboard_wizard import WizardRunResult

        return WizardRunResult(exit_code=0)

    monkeypatch.setattr("yoke_cli.config.onboard_wizard.run_wizard", fake_run_wizard)
    monkeypatch.setattr(
        "yoke_cli.commands.adapters.onboard_interactive.require_foreground_terminal",
        lambda: None,
    )
    monkeypatch.setattr(
        "yoke_cli.config.onboard_wizard.is_interactive", lambda *_: True
    )

    rc = yoke_operations_cli.main(
        [
            "setup",
            "--post-install",
            "--env",
            "prod",
            "--api-url",
            "https://api.test",
            "tok",
        ]
    )

    assert rc == 0
    assert captured["post_install"] is True


def test_repeated_retry_keeps_history_until_check_completes(monkeypatch):
    import threading

    app = _app()
    release = threading.Event()
    calls = []
    monkeypatch.setattr(
        app, "_check_install", lambda: ({}, "install_check_failed: retry")
    )

    def slow_check():
        calls.append(True)
        assert release.wait(5)
        return {"login_verified": True}, ""

    async def scenario():
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            monkeypatch.setattr(app, "_check_install", slow_check)
            try:
                await pilot.press("enter", "enter")
                assert len(app._history) == 1
            finally:
                release.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert calls == [True]
            assert all(view.step != STEP_INSTALL for view in app._history)

    asyncio.run(scenario())
