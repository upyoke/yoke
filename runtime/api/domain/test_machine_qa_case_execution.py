from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from runtime.api.domain.machine_qa_baseline_group_test_support import (
    materialize_installer_campaign,
)
from yoke_core.domain.handlers.machine_qa_case import (
    _record_machine_case_result,
)
from yoke_core.domain.machine_qa_execution import MachineCaseResult
from yoke_core.domain.qa_artifact_handle import local_handle, parse_handle
from yoke_core.domain.qa_case_execution_context import (
    get_case_execution_context,
)
from yoke_core.domain.ssh_mac_terminal_capture import verify_terminal_bridge
from yoke_core.domain.ssh_mac_host_control import SshMacHostControl


def test_terminal_bridge_verification_exercises_all_control_surfaces() -> None:
    commands = []

    def run(command: str, **_kwargs):
        commands.append(command)
        stdout = (
            "yoke-terminal-bridge-ready"
            if command.startswith("tmux capture-pane")
            else "445"
            if "return id of front window" in command
            else "cG5n"
            if command.startswith("/bin/test -s ")
            else ""
        )
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    ok, evidence, error_code = verify_terminal_bridge(run)

    assert ok is True
    assert error_code is None
    assert evidence == {
        "pty": True,
        "terminal_control": True,
        "screenshot_capture": True,
        "sample_artifact_retained": False,
    }
    terminal_capture = next(
        command
        for command in commands
        if "/usr/bin/osascript" in command and "/usr/sbin/screencapture" in command
    )
    assert 'tell application "Terminal"' in terminal_capture
    assert not any(
        command.startswith("/usr/sbin/screencapture") for command in commands
    )
    assert any(command.startswith("/bin/test -s ") for command in commands)
    assert sum("close window id " in command for command in commands) == 2
    assert any(command.startswith("rm -f ") for command in commands)
    assert any(command.startswith("tmux kill-session") for command in commands)


def test_required_terminal_completion_has_distinct_not_reached_outcome(
    tmp_path: Path,
    monkeypatch,
) -> None:
    control = SshMacHostControl.__new__(SshMacHostControl)
    control.material = SimpleNamespace(
        settings={"resource_name": "mac-mini-lab"},
    )
    control._run = lambda command, **_kwargs: SimpleNamespace(
        returncode=0,
        stdout=(
            "tmux"
            if command == "if command -v tmux >/dev/null 2>&1; then printf tmux; "
            "elif command -v screen >/dev/null 2>&1; then printf screen; fi"
            else "445"
            if "return id of front window" in command
            else ""
        ),
        stderr="",
    )
    monkeypatch.setattr(
        "yoke_core.domain.ssh_mac_host_control.machine_config.yoke_home",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        "yoke_core.domain.ssh_mac_terminal_legacy.wait_for_text",
        lambda *_args, **_kwargs: None,
    )

    result = control.run_terminal_case(
        entry_surface="yoke onboard",
        required_completion="review",
        steps=[{"key": "review", "expect": "Review"}],
        capture_checkpoints=[],
    )

    assert result.ok is False
    assert result.error_code == "terminal_completion_not_reached"


def test_machine_result_records_exact_outcome_and_canonical_artifacts(
    test_db,
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
    materialized = materialize_installer_campaign(test_db, item_id=42)
    requirement_id = next(
        int(row["id"])
        for row in materialized
        if row["plan_case_key"] == "default-add-yoke-to-my-path"
    )
    case = get_case_execution_context(
        test_db,
        requirement_id=requirement_id,
    )
    assert "lane_commit_sha" not in case
    screenshot = tmp_path / "welcome.png"
    screenshot.write_bytes(b"png-evidence")
    result = MachineCaseResult(
        case_outcome="needs_review",
        verdict="pending",
        capture_degraded_reason=None,
        evidence={
            "machine": "mac-mini-lab",
            "steps": [
                {
                    "key": "welcome",
                    "transcript": "Your operating system for software delivery",
                    "artifact_handle": local_handle(
                        str(screenshot.resolve()),
                        "image/png",
                    ),
                }
            ],
        },
    )

    recorded = _record_machine_case_result(
        test_db,
        case=case,
        result=result,
        duration_ms=12,
    )

    run = test_db.execute(
        "SELECT verdict,case_outcome,raw_result FROM qa_runs WHERE id=%s",
        (recorded["run_id"],),
    ).fetchone()
    assert (run["verdict"], run["case_outcome"]) == (None, "needs_review")
    assert json.loads(run["raw_result"])["evidence"]["machine"] == "mac-mini-lab"
    artifacts = test_db.execute(
        "SELECT artifact_type,artifact_handle FROM qa_artifacts "
        "WHERE qa_run_id=%s ORDER BY artifact_type",
        (recorded["run_id"],),
    ).fetchall()
    assert [row["artifact_type"] for row in artifacts] == [
        "machine_evidence",
        "terminal_screenshot",
    ]
    handles = [parse_handle(row["artifact_handle"]) for row in artifacts]
    assert all(handle["backend"] == "local" for handle in handles)
    assert all(Path(handle["path"]).is_file() for handle in handles)
    assert screenshot.exists() is False
    assert recorded["evidence_count"] == 2
