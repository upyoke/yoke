"""Setup keeps the failing operation's cause visible through recovery and exit."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from textual.widgets import Static

from yoke_cli.commands.adapters import onboard_apply
from yoke_cli.config import onboard
from yoke_cli.config.onboard_wizard import WizardRunResult
from yoke_cli.config.onboard_wizard_widgets import SelectionList

from runtime.api.cli.onboard_wizard_test_helpers import make_app, stub_path_doctor


@pytest.mark.parametrize(
    ("reason", "visible_reason", "recovery"),
    [
        (
            "network error reaching GitHub; check your connection and try again",
            "network error reaching GitHub; check your connection and try again",
            "Try again",
        ),
        (
            "actor 37 lacks 'project.create' on org 'Acme' (id 1)",
            "You lack project.create rights for Acme. Contact your Yoke administrator.",
            "Change answers",
        ),
        (
            "repo already exists and has content; choose a different repository name",
            "repo already exists and has content; choose a different repository name",
            "Change answers",
        ),
    ],
)
def test_apply_cause_survives_report_screen_and_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
    reason: str,
    visible_reason: str,
    recovery: str,
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    stub_path_doctor(monkeypatch)
    app, preview = make_app()
    app.result.project_mode = "machine-only"
    app.result.config_path = str(tmp_path / "config.json")
    app._review_plan = preview(
        app.result.build_report_kwargs(apply=False, check_identity=False)
    )

    def build_report(**kwargs):
        if kwargs["apply"]:
            kwargs["progress"]("set-active-env", kwargs["env_name"], "running")
            raise onboard.OnboardError(reason)
        return preview(kwargs)

    monkeypatch.setattr(onboard, "build_report", build_report)
    app._apply_report = onboard_apply.apply_with_durable_report

    async def scenario() -> None:
        async with app.run_test() as pilot:
            app._start_apply()
            await app.workers.wait_for_complete()
            await pilot.pause()
            body = "\n".join(str(widget.render()) for widget in app.query(Static))
            assert f"Cause: {visible_reason}" in body
            assert "What to do" in body
            assert recovery in [row.label for row in app.query_one(SelectionList).rows]
            assert "summary above" not in body.lower()
            app._on_apply_failure("exit")

    asyncio.run(scenario())
    assert app.exit_code == 1
    payload = json.loads(Path(app.report_path).read_text())
    assert payload["error"] == reason
    assert payload["steps"][1]["error"] == reason
    assert payload["final_status"] == "failed"
    onboard_apply.print_failure_summary(
        WizardRunResult(
            exit_code=app.exit_code,
            error=app.last_error,
            failed_step=app.failed_step,
            report_path=app.report_path,
            resume_command=app.resume_command,
        )
    )
    terminal = capsys.readouterr().err
    assert f"error: {visible_reason}" in terminal
    assert f"resume: {app.resume_command}" in terminal
    assert "summary above" not in terminal.lower()
