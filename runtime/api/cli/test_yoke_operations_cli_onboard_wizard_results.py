"""Review result-state coverage for the ``yoke onboard`` wizard."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

pytest.importorskip("textual")

from yoke_cli.config import onboard_apply_report  # noqa: E402
from yoke_cli.config.onboard_wizard import WizardApplyError  # noqa: E402
from yoke_cli.config.onboard_wizard_widgets import SelectionList  # noqa: E402

from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    advance_past_path,
    make_app,
    stub_path_doctor,
)


@pytest.fixture(autouse=True)
def _stub_path_doctor(monkeypatch):
    stub_path_doctor(monkeypatch)


def _plan(kwargs: dict, *, applied: bool) -> dict:
    return {
        "operation": "onboard",
        "mode": kwargs["mode"],
        "project_mode": kwargs["project_mode"],
        "applied": applied,
        "config_path": kwargs["config_path"],
        "plan": {"steps": [
            {"action": "create-or-validate-dir", "target": "/home/.yoke"},
            {"action": "set-active-env", "target": kwargs["env_name"]},
        ]},
        "identity": {"checked": False, "ok": None},
        "next_steps": [],
    }


def _failed_saved_project_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict, Path]:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    checkout = tmp_path / "fresh-checkout"
    kwargs = {
        "config_path": str(tmp_path / "config.json"),
        "env_name": "stage",
        "api_url": "https://api.stage.example",
        "token_source_kind": "prompt",
        "mode": "quick",
        "apply": True,
        "check_identity": True,
        "project_mode": "clone-remote",
        "project_remote_url": "https://github.com/acme/widget.git",
        "project_checkout": str(checkout),
    }
    writer = onboard_apply_report.ApplyReportWriter.start(
        _plan(kwargs, applied=False), kwargs
    )
    checkout.mkdir()
    writer.fail(RuntimeError("network error reaching GitHub"))
    return writer.summary(), checkout


async def _apply_machine_only(app, expected_labels: list[str]) -> None:
    async with app.run_test() as pilot:
        await advance_past_path(pilot)
        await pilot.press("down")
        await pilot.press("enter")
        for _ in range(4):
            await pilot.press("down")
        await pilot.press("enter")
        await pilot.press("enter")
        # Apply runs in a worker thread; wait for it before reading the screen.
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert [row.label for row in app.query_one(SelectionList).rows] == expected_labels


def test_apply_failure_stays_in_tui_until_exit() -> None:
    app, _spy = make_app()

    def fail_on_apply(kwargs: dict, progress=None) -> dict:
        if kwargs["apply"]:
            raise WizardApplyError(
                "repo already exists and has content",
                failed_step="03-project-create",
                report_path="/tmp/onboard-report.json",
                resume_command="yoke onboard",
            )
        return _plan(kwargs, applied=False)

    app._apply_report = fail_on_apply
    # A content collision is not retryable (same name fails again), so the menu
    # is Change answers / Exit — no "Try again".
    asyncio.run(_apply_machine_only(app, ["Change answers", "Exit"]))

    assert app.exit_code == 1
    assert app.last_error == "repo already exists and has content"
    assert app.report_path == "/tmp/onboard-report.json"


def test_apply_failure_offers_retry_when_retryable() -> None:
    app, _spy = make_app()

    def fail_transient(kwargs: dict, progress=None) -> dict:
        if kwargs["apply"]:
            raise WizardApplyError(
                "network error reaching GitHub",
                failed_step="03-project-create",
                report_path="/tmp/onboard-report.json",
                resume_command="yoke onboard",
            )
        return _plan(kwargs, applied=False)

    app._apply_report = fail_transient
    # A transient failure can plausibly succeed on retry, so "Try again" leads.
    asyncio.run(_apply_machine_only(app, ["Try again", "Change answers", "Exit"]))
    assert app.exit_code == 1


def test_apply_retry_success_clears_prior_failure() -> None:
    app, _spy = make_app()
    apply_calls = 0

    def fail_then_succeed(kwargs: dict, progress=None) -> dict:
        nonlocal apply_calls
        if kwargs["apply"]:
            apply_calls += 1
            if apply_calls == 1:
                raise WizardApplyError(
                    "network error reaching install bundle",
                    failed_step="09-project-install-scaffold",
                    report_path="/tmp/failed-onboard-report.json",
                    resume_command="yoke onboard --resume run-failed",
                )
        report = _plan(kwargs, applied=bool(kwargs["apply"]))
        report["apply_report"] = {"path": "/tmp/success-onboard-report.json"}
        return report

    app._apply_report = fail_then_succeed

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("down")
            await pilot.press("enter")
            for _ in range(4):
                await pilot.press("down")
            await pilot.press("enter")
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.exit_code == 1
            assert app.last_error == "network error reaching install bundle"
            assert [row.label for row in app.query_one(SelectionList).rows] == [
                "Try again", "Change answers", "Exit",
            ]

            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert [row.label for row in app.query_one(SelectionList).rows] == [
                "Exit", "Show report",
            ]
            assert app.exit_code == 0
            assert app.last_error is None
            assert app.failed_step is None
            assert app.resume_command is None
            assert app.report_path == "/tmp/success-onboard-report.json"

            await pilot.press("enter")

    asyncio.run(scenario())

    assert apply_calls == 2
    assert app.exit_code == 0
    assert app.last_error is None


def test_apply_failure_offers_saved_report_recovery_actions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary, _checkout = _failed_saved_project_report(tmp_path, monkeypatch)
    app, _spy = make_app()
    app.last_error = "repo already exists and has content"
    app.failed_step = str(summary["failed_step"])
    app.report_path = str(summary["path"])
    app.resume_command = str(summary["resume_command"])

    async def scenario() -> None:
        async with app.run_test() as pilot:
            app._goto_apply_failure()
            await pilot.pause()
            assert [row.label for row in app.query_one(SelectionList).rows] == [
                "Resume from cloned folder",
                "Start over",
                "Change answers",
                "Exit",
            ]

    asyncio.run(scenario())


def test_apply_failure_resume_reuses_saved_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary, _checkout = _failed_saved_project_report(tmp_path, monkeypatch)
    app, _spy = make_app()
    app.last_error = "repo already exists and has content"
    app.failed_step = str(summary["failed_step"])
    app.report_path = str(summary["path"])
    app.resume_command = str(summary["resume_command"])
    calls: list[dict] = []

    def succeed(kwargs: dict, progress=None) -> dict:
        calls.append(dict(kwargs))
        report = _plan(kwargs, applied=bool(kwargs["apply"]))
        report["apply_report"] = {"path": str(summary["path"])}
        return report

    app._apply_report = succeed

    async def scenario() -> None:
        async with app.run_test() as pilot:
            app._goto_apply_failure()
            await pilot.pause()
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()

    asyncio.run(scenario())

    assert calls
    assert calls[0]["resume_run_id"] == Path(str(summary["path"])).stem
    assert calls[0]["resume_payload"]["run_id"] == calls[0]["resume_run_id"]


def test_apply_failure_start_over_waits_for_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary, checkout = _failed_saved_project_report(tmp_path, monkeypatch)
    app, _spy = make_app()
    app.last_error = "repo already exists and has content"
    app.failed_step = str(summary["failed_step"])
    app.report_path = str(summary["path"])
    app.resume_command = str(summary["resume_command"])

    async def scenario() -> None:
        async with app.run_test() as pilot:
            app._goto_apply_failure()
            await pilot.pause()
            await pilot.press("down")
            await pilot.press("enter")
            await pilot.pause()
            assert checkout.is_dir()
            assert [row.label for row in app.query_one(SelectionList).rows] == [
                "Remove checkout",
                "Cancel",
            ]
            await pilot.press("enter")
            await pilot.pause()

    asyncio.run(scenario())

    assert not checkout.exists()


def test_apply_success_stays_in_tui_with_report_action() -> None:
    app, _spy = make_app()

    def succeed(kwargs: dict, progress=None) -> dict:
        report = _plan(kwargs, applied=bool(kwargs["apply"]))
        report["apply_report"] = {"path": "/tmp/onboard-report.json"}
        return report

    app._apply_report = succeed
    asyncio.run(_apply_machine_only(app, ["Exit", "Show report"]))

    assert app.exit_code == 0
    assert app.report_path == "/tmp/onboard-report.json"


def test_applying_screen_updates_steps_live() -> None:
    """A progress event flips one Applying row in place (pending -> running ->
    done) — the live feedback that replaces the frozen Review screen."""
    from yoke_cli.config.onboard_wizard_steps import APPLY_STATUS_GLYPHS as G

    app, _spy = make_app()
    sel = "#applystep-00-create-or-validate-dir"

    async def scenario() -> None:
        async with app.run_test() as pilot:
            app._review_plan = {"plan": {"steps": [
                {"action": "create-or-validate-dir", "target": "/home/.yoke"},
                {"action": "set-active-env", "target": "stage"},
            ]}}
            app._apply_steps = app._applying_step_model()
            app._goto_applying()
            await pilot.pause()
            assert G["pending"] in str(app.query_one(sel).render())

            app._set_apply_step_status("create-or-validate-dir", "/home/.yoke", "running")
            await pilot.pause()
            assert G["running"] in str(app.query_one(sel).render())

            app._set_apply_step_status("create-or-validate-dir", "/home/.yoke", "done")
            await pilot.pause()
            assert G["done"] in str(app.query_one(sel).render())

    asyncio.run(scenario())


def test_applying_screen_updates_use_ascii_in_plain_mode(monkeypatch) -> None:
    monkeypatch.setenv("YOKE_ONBOARD_FORCE_PLAIN", "1")
    app, _spy = make_app()
    sel = "#applystep-00-create-or-validate-dir"

    async def scenario() -> None:
        async with app.run_test() as pilot:
            app._review_plan = {"plan": {"steps": [
                {"action": "create-or-validate-dir", "target": "/home/.yoke"},
            ]}}
            app._apply_steps = app._applying_step_model()
            app._goto_applying()
            await pilot.pause()
            assert "  o " in str(app.query_one(sel).render())
            assert "○" not in str(app.query_one(sel).render())

            app._set_apply_step_status("create-or-validate-dir", "/home/.yoke", "done")
            await pilot.pause()
            assert "  + " in str(app.query_one(sel).render())
            assert "✔" not in str(app.query_one(sel).render())

    asyncio.run(scenario())


def test_ctrl_c_suppressed_during_apply() -> None:
    """Ctrl-C while applying must not tear the TUI down mid-mutation."""
    app, _spy = make_app()

    def succeed(kwargs: dict, progress=None) -> dict:
        return _plan(kwargs, applied=bool(kwargs["apply"]))

    app._apply_report = succeed

    # Mid-apply state: quitting is suppressed.
    app._applying = True
    app.action_quit_wizard()
    assert app.cancelled is False
    # Once apply finishes, quitting works again.
    app._applying = False
    app.action_quit_wizard()
    assert app.cancelled is True
