"""Pilot-driven coverage for the wizard's Install + PATH front steps.

The PATH doctor is monkeypatched at the wizard boundary so no scenario touches
the real shell, HOME, or startup files. Each scenario is an async coroutine run
under ``asyncio.run`` so the suite needs no async-test plugin.
"""

from __future__ import annotations

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


def _diagnosis(*, needs_fix: bool) -> path_doctor.PathDiagnosis:
    resolved = [path_doctor.ToolResolution(t, None if needs_fix else f"/bin/{t}")
                for t in path_doctor.TOOLS]
    return path_doctor.PathDiagnosis(
        current_shell="zsh",
        tool_bin_dir="/home/u/.local/bin",
        current_on_path=not needs_fix,
        current_resolved=resolved,
        startup_file="/home/u/.zprofile",
        future_adds_bin=not needs_fix,
        managed_block_present=not needs_fix,
        future_resolved=resolved,
        needs_fix=needs_fix,
        ssh_startup_file="/home/u/.zshenv",
        ssh_adds_bin=not needs_fix,
        ssh_managed_block_present=not needs_fix,
        ssh_resolved=resolved,
        ssh_needs_fix=needs_fix,
    )


def _all_clear_diagnosis() -> path_doctor.PathDiagnosis:
    return _diagnosis(needs_fix=False)


class _ApplySpy:
    def __init__(self) -> None:
        self.apply_calls: list[tuple] = []
        self.verify_fresh_calls: list = []
        self.verify_ssh_calls: list = []

    def apply_fix(self, startup, tool_bin_dir) -> bool:
        self.apply_calls.append((startup, tool_bin_dir))
        return True

    def verify_fresh_login(self, shell=None):
        self.verify_fresh_calls.append(shell)
        return _diagnosis(needs_fix=False).future_resolved

    def verify_ssh_command(self, shell=None):
        self.verify_ssh_calls.append(shell)
        return _diagnosis(needs_fix=False).future_resolved


@pytest.fixture
def stub_path(monkeypatch):
    """Install a needs-fix diagnosis and a spy over apply_fix / verify_fresh_login."""
    spy = _ApplySpy()
    monkeypatch.setattr(path_doctor, "diagnose", lambda **_: _diagnosis(needs_fix=True))
    monkeypatch.setattr(path_doctor, "tool_bin_dir", lambda env=None: "/home/u/.local/bin")
    monkeypatch.setattr(path_doctor, "current_shell", lambda env=None: "zsh")
    monkeypatch.setattr(path_doctor, "apply_fix", spy.apply_fix)
    monkeypatch.setattr(path_doctor, "verify_fresh_login", spy.verify_fresh_login)
    monkeypatch.setattr(path_doctor, "verify_ssh_command", spy.verify_ssh_command)
    return spy


def _app(defaults: WizardDefaults | None = None) -> OnboardWizardApp:
    return OnboardWizardApp(
        defaults=defaults or WizardDefaults(
            config_path="/tmp/cfg.json", env_name="prod",
            api_url="https://api.test", token="actor-token",
        ),
        apply_report=lambda kwargs: {"plan": {"steps": []}},
    )


def _visible_static_text(app: OnboardWizardApp) -> str:
    return "\n".join(str(widget.render()) for widget in app.query(Static))


def test_stepper_order_uses_consistent_noun_labels() -> None:
    # The rail uses nouns (the subject of each step): Install · Account · GitHub
    # · Project · Review. PATH folds into Install; internal step ids are unchanged.
    labels = [label for _id, label in STEPPER_ORDER]
    assert labels == ["Install", "Account", "GitHub", "Project", "Review"]
    assert STEPPER_ORDER[0] == ("install", "Install")
    assert STEPPER_ORDER[1] == ("connect", "Account")
    assert STEPPER_ORDER[-1] == ("finish", "Review")


def test_plain_text_replaces_screen_unsafe_glyphs() -> None:
    assert plain_text("☀ ✓ ✗ → ─ │ — … ·") == "* OK x -> - | - ... -"


def test_screen_terminal_uses_ascii_visible_glyphs(monkeypatch, stub_path) -> None:
    monkeypatch.setenv("YOKE_ONBOARD_FORCE_PLAIN", "1")
    monkeypatch.setenv("TERM", "screen-256color")
    monkeypatch.setenv("STY", "1234.yoke-test")
    app = _app(WizardDefaults(
        config_path="/tmp/cfg.json", env_name="prod", api_url="https://api.test",
        token="actor-token", post_install=True,
    ))

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.screen.has_class("plain-glyphs")
            body = app.query_one("#onboard-body")
            assert not isinstance(body, VerticalScroll)
            text = _visible_static_text(app)
            assert "* Yoke" in text
            assert "up/down navigate" in text
            assert ">  Continue" in text
            assert not (UNSAFE_SCREEN_GLYPHS & set(text))

            await pilot.press("enter")  # install summary: continue
            await pilot.pause()
            text = _visible_static_text(app)
            assert "x uv" in text
            assert "x yoke" in text
            assert ">  Add yoke to my PATH" in text
            assert not (UNSAFE_SCREEN_GLYPHS & set(text))

            app._goto_project_mode()
            await pilot.pause()
            text = _visible_static_text(app)
            assert "advanced - contributors" in text
            assert not (UNSAFE_SCREEN_GLYPHS & set(text))

    asyncio.run(scenario())


def test_dumb_terminal_uses_ascii_visible_glyphs(monkeypatch, stub_path) -> None:
    monkeypatch.setenv("YOKE_ONBOARD_FORCE_PLAIN", "1")
    monkeypatch.setenv("TERM", "dumb")
    monkeypatch.delenv("STY", raising=False)
    app = _app(WizardDefaults(
        config_path="/tmp/cfg.json", env_name="prod", api_url="https://api.test",
        token="actor-token", post_install=True,
    ))

    async def scenario() -> None:
        async with app.run_test() as pilot:
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


def test_wizard_opens_on_path_diagnosis(stub_path) -> None:
    app = _app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            # PATH diagnosis highlights the Install segment (PATH is part of it).
            assert app.query_one(Stepper).active == STEP_INSTALL

    asyncio.run(scenario())


def test_preview_apply_writes_managed_block(stub_path) -> None:
    app = _app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("down")   # path diagnosis: "Show the exact change first"
            await pilot.press("enter")  # -> preview + consent
            await pilot.pause()
            await pilot.press("enter")  # preview: "Apply this change"
            await pilot.pause()

    asyncio.run(scenario())

    assert stub_path.apply_calls, "apply_fix was not called"
    _startup, tool_bin_dir = stub_path.apply_calls[0]
    assert tool_bin_dir == "/home/u/.local/bin"
    assert [str(call[0]) for call in stub_path.apply_calls] == [
        "/home/u/.zprofile",
        "/home/u/.zshenv",
    ]
    assert stub_path.verify_fresh_calls == ["zsh"]
    assert stub_path.verify_ssh_calls == ["zsh"]


def test_preview_choose_different_returns_to_path_diagnosis(stub_path) -> None:
    app = _app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            diagnosis_view = app._history[-1]
            diagnosis_depth = len(app._history)
            for _ in range(3):
                await pilot.press("down")
                await pilot.press("enter")
                await pilot.pause()
                await pilot.press("down")
                await pilot.press("enter")
                await pilot.pause()

                assert app._history[-1] is diagnosis_view
                assert len(app._history) == diagnosis_depth
                assert app.query_one(Stepper).active == STEP_INSTALL
                assert "Add Yoke to your PATH" in _visible_static_text(app)

    asyncio.run(scenario())
    assert stub_path.apply_calls == []


def test_fix_choice_applies_directly(stub_path) -> None:
    app = _app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("enter")  # path diagnosis: "Add yoke to my PATH"
            await pilot.pause()

    asyncio.run(scenario())

    assert stub_path.apply_calls, "Add-to-PATH row did not call apply_fix"


def test_fix_choice_accepts_space(stub_path) -> None:
    app = _app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("space")  # path diagnosis: "Add yoke to my PATH"
            await pilot.pause()

    asyncio.run(scenario())

    assert stub_path.apply_calls, "Space did not choose the selected PATH row"


def test_path_continue_accepts_ctrl_j(monkeypatch) -> None:
    monkeypatch.setattr(path_doctor, "diagnose", lambda **_: _all_clear_diagnosis())
    monkeypatch.setattr(
        path_doctor, "verify_fresh_login",
        lambda shell=None: _all_clear_diagnosis().future_resolved,
    )
    monkeypatch.setattr(
        path_doctor, "verify_ssh_command",
        lambda shell=None: _all_clear_diagnosis().ssh_resolved,
    )
    app = _app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("ctrl+j")  # path diagnosis: "Continue"
            await pilot.pause()
            # Continue advances out of the Install/PATH segment into onboarding.
            assert app.query_one(Stepper).active != STEP_INSTALL

    asyncio.run(scenario())


def test_post_install_opens_on_install_summary(stub_path) -> None:
    app = _app(WizardDefaults(
        config_path="/tmp/cfg.json", env_name="prod", api_url="https://api.test",
        token="actor-token", post_install=True,
    ))

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one(Stepper).active == "install"
            await pilot.press("enter")  # install summary: continue
            await pilot.pause()
            # PATH diagnosis stays under the Install segment.
            assert app.query_one(Stepper).active == STEP_INSTALL

    asyncio.run(scenario())


def test_onboard_post_install_flag_parses(monkeypatch, capsys) -> None:
    captured: dict = {}

    def fake_run_wizard(defaults, *, apply_report):
        captured["post_install"] = defaults.post_install
        from yoke_cli.config.onboard_wizard import WizardRunResult

        return WizardRunResult(exit_code=0)

    monkeypatch.setattr(
        "yoke_cli.config.onboard_wizard.run_wizard", fake_run_wizard
    )
    monkeypatch.setattr(
        "yoke_cli.config.onboard_wizard.is_interactive", lambda *_: True
    )

    rc = yoke_operations_cli.main([
        "onboard", "--post-install",
        "--env", "prod", "--api-url", "https://api.test", "tok",
    ])

    assert rc == 0
    assert captured["post_install"] is True
