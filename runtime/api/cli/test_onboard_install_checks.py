"""Automatic Install failure boundaries and summary preservation."""

from dataclasses import replace

import pytest

from yoke_cli.config import path_doctor, onboard_apply_path, onboard_path_plan
from yoke_cli.config.onboard_wizard_path import PathFlow
from yoke_cli.config.setup_run_facts import RunFacts
from runtime.api.cli.test_yoke_operations_cli_onboard_wizard_path import _diagnosis


@pytest.mark.parametrize("tool", path_doctor.TOOLS)
def test_missing_required_tool_has_named_recovery(monkeypatch, tool):
    diagnosis = _diagnosis(needs_fix=False)
    diagnosis = replace(
        diagnosis,
        future_resolved=[
            path_doctor.ToolResolution(row.name, None if row.name == tool else row.path)
            for row in diagnosis.future_resolved
        ],
    )
    monkeypatch.setattr(path_doctor, "diagnose", lambda: diagnosis)
    plan, error = PathFlow()._check_install()
    assert "install_required_tool_missing" in error
    assert tool in error
    assert "installer again" in error
    assert not plan["login_verified"]


def test_optional_harness_does_not_block_install(monkeypatch):
    diagnosis = _diagnosis(needs_fix=False)
    monkeypatch.setattr(
        path_doctor,
        "diagnose",
        lambda: replace(
            diagnosis,
            future_resolved=[
                *diagnosis.future_resolved,
                path_doctor.ToolResolution("codex", None),
            ],
        ),
    )
    plan, error = PathFlow()._check_install()
    assert not error
    assert plan["login_verified"]


def test_shell_changes_survive_failure_and_are_named_in_summary(monkeypatch, tmp_path):
    profile = tmp_path / ".profile"
    monkeypatch.setattr(path_doctor, "supported_startup_files", lambda home: (profile,))

    def fail_after_write():
        profile.write_text("export PATH=toolbin:$PATH\n")
        raise OSError("uv_shell_update_failed: permission denied")

    monkeypatch.setattr(path_doctor, "update_shell", fail_after_write)
    monkeypatch.setattr(path_doctor, "diagnose", lambda: _diagnosis(needs_fix=True))
    plan, error = PathFlow()._check_install()
    assert "uv_shell_update_failed" in error
    assert plan["changed_files"] == [str(profile)]
    assert str(profile) in onboard_path_plan.shell_change_lines(plan)[0]


def test_completed_install_is_carried_without_reapplying(monkeypatch):
    plan = {
        "targets": [{"path": "uv tool update-shell"}],
        "login_verified": True,
        "changed_files": ["/example/.profile"],
    }
    monkeypatch.setattr(
        path_doctor, "update_shell", lambda: pytest.fail("already applied")
    )
    report = {}
    onboard_apply_path.apply(plan, progress=None, report=report)
    assert report["path_repair"] == plan
    assert onboard_path_plan.steps(plan) == []


def test_retry_preserves_shell_changes_and_finish_summary(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from yoke_cli.config.onboard_wizard_finish_flow import FinishBodyFlow

    class Flow(PathFlow):
        result = SimpleNamespace(path_repair={"changed_files": ["/example/.profile"]})
        connected = False
        _run_facts = RunFacts()

        def _start_connect(self):
            self.connected = True

    flow = Flow()
    flow._history = []
    monkeypatch.setattr(flow, "_check_install", lambda: ({"login_verified": True}, ""))
    asyncio.run(flow._run_install())
    assert flow.connected
    assert flow.result.path_repair["changed_files"] == ["/example/.profile"]
    finish = FinishBodyFlow()
    finish.result = SimpleNamespace(
        path_repair=flow.result.path_repair,
        yoke_token_verification=None,
        hosting_verification=None,
        machine_finish=None,
    )
    monkeypatch.setattr(
        "yoke_cli.config.onboard_wizard_finish_flow.machine_finish_lines", lambda _: []
    )
    assert "Shell file updated: /example/.profile" in finish._review_status_lines()


def test_text_summary_lists_actual_shell_changes(monkeypatch):
    from yoke_cli.config.onboard_report_render import render_human

    monkeypatch.setattr(
        "yoke_cli.config.onboard_reuse_feedback.grouped_lines_for_plan", lambda _: {}
    )
    report = {
        "mode": "local",
        "config_path": "/example/config.json",
        "applied": True,
        "plan": {"steps": []},
        "identity": {},
        "next_steps": [],
        "path_repair": {"changed_files": ["/example/.profile"]},
    }
    assert "Shell file updated: /example/.profile" in render_human(report)
