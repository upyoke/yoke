"""Pilot-driven coverage for the wizard's Install + PATH front steps."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from textual.widgets import Rule, Static  # noqa: E402
from textual.containers import VerticalScroll  # noqa: E402

from yoke_cli import main as yoke_operations_cli  # noqa: E402
from yoke_cli.config import onboard_wizard_path, path_doctor  # noqa: E402
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
    resolved = [
        path_doctor.ToolResolution(t, None if needs_fix else f"/bin/{t}")
        for t in path_doctor.TOOLS
    ]
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
        login_needs_fix=needs_fix,
        managed_path_dirs=("/home/u/.local/bin",),
    )


def _all_clear_diagnosis() -> path_doctor.PathDiagnosis:
    return _diagnosis(needs_fix=False)


@pytest.fixture
def stub_path(monkeypatch):
    """Install a needs-fix diagnosis and refuse writes before Review."""
    monkeypatch.setattr(path_doctor, "diagnose", lambda **_: _diagnosis(needs_fix=True))
    monkeypatch.setattr(
        path_doctor,
        "apply_fix",
        lambda *_args, **_kwargs: pytest.fail("PATH was written before Review Apply"),
    )


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
            assert ">  Add Yoke and harness CLIs to PATH" in text
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
            assert app.query_one(Stepper).active == STEP_INSTALL

    asyncio.run(scenario())


def test_preview_queues_exact_managed_block_for_review(stub_path) -> None:
    app = _app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("down")  # path diagnosis: "Show the exact change first"
            await pilot.press("enter")  # -> preview + consent
            await pilot.pause()
            text = _visible_static_text(app)
            assert "/home/u/.zprofile" in text
            assert "/home/u/.zshenv" in text
            assert "non-login/SSH" in text
            assert "/home/u/.local/bin" in text
            await pilot.press("enter")  # preview: add the writes to Review
            await pilot.pause()

    asyncio.run(scenario())
    assert app.result.path_repair["targets"] == [
        {"surface": "login", "path": "/home/u/.zprofile"},
        {"surface": "ssh", "path": "/home/u/.zshenv"},
    ]


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
                assert "Put Yoke and your harness CLIs on PATH" in (
                    _visible_static_text(app)
                )

    asyncio.run(scenario())


def test_add_path_reviews_both_files_then_applies(monkeypatch, stub_path) -> None:
    applied: dict = {}

    def fake_apply(plan, *, progress, report):
        applied["ok"] = True
        report["path_repair"] = {**plan, "login_verified": True, "ssh_verified": True}

    monkeypatch.setattr("yoke_cli.config.onboard_apply_path.apply", fake_apply)
    app = _app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("space")  # Add-PATH
            await pilot.pause()
            text = _visible_static_text(app)
            assert "/home/u/.zprofile" in text and "/home/u/.zshenv" in text
            assert app.query_one(Stepper).active == STEP_INSTALL
            assert not applied
            await pilot.press("enter")  # Apply writes now
            await pilot.pause()
            assert applied["ok"]
            assert app.query_one(Stepper).active != STEP_INSTALL

    asyncio.run(scenario())


def test_path_continue_accepts_ctrl_j(monkeypatch) -> None:
    monkeypatch.setattr(path_doctor, "diagnose", lambda **_: _all_clear_diagnosis())
    monkeypatch.setattr(
        path_doctor,
        "verify_fresh_login",
        lambda shell=None, **_: _all_clear_diagnosis().future_resolved,
    )
    monkeypatch.setattr(
        path_doctor,
        "verify_ssh_command",
        lambda shell=None, **_: _all_clear_diagnosis().ssh_resolved,
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
            await pilot.pause()
            assert app.query_one(Stepper).active == "install"
            await pilot.press("enter")  # install summary: continue
            await pilot.pause()
            # PATH diagnosis stays under the Install segment.
            assert app.query_one(Stepper).active == STEP_INSTALL

    asyncio.run(scenario())


def test_source_install_summary_does_not_claim_ambient_wheel_version() -> None:
    rendered = "\n".join(
        str(widget.render()) for widget in onboard_wizard_path.install_summary_body()
    )

    assert "Yoke source checkout is installed." in rendered


def test_onboard_post_install_flag_parses(monkeypatch, capsys) -> None:
    captured: dict = {}

    def fake_run_wizard(defaults, *, apply_report):
        captured["post_install"] = defaults.post_install
        from yoke_cli.config.onboard_wizard import WizardRunResult

        return WizardRunResult(exit_code=0)

    monkeypatch.setattr("yoke_cli.config.onboard_wizard.run_wizard", fake_run_wizard)
    monkeypatch.setattr(
        "yoke_cli.config.onboard_wizard.is_interactive", lambda *_: True
    )

    rc = yoke_operations_cli.main(
        [
            "onboard",
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
