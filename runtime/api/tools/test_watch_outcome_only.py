"""Outcome-only watcher output is shared by merge and deploy wait modes."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

from yoke_core.tools import (
    _watch_capture_binding,
    _watch_runner,
    watch_deploy,
    watch_merge,
)
from yoke_core.tools import gate_stall_report
from yoke_core.tools._watch_wait_mode import WatchWaitMode
from yoke_core.tools._watch_throttle import Classification, LineClass
from yoke_core.tools import watch_tail
from yoke_core.tools._watch_terminal_outcome import format_terminal_outcome


WATCHERS = (
    ("merge", watch_merge.classify_merge_line),
    ("deploy", watch_deploy.classify_deploy_line),
)


def _child(tmp_path: Path, lines: list[str], exit_code: int) -> Path:
    script = tmp_path / f"child-{exit_code}.py"
    body = "import sys\n" + "".join(f"print({line!r})\n" for line in lines)
    script.write_text(body + f"sys.exit({exit_code})\n", encoding="utf-8")
    return script


@pytest.mark.parametrize(("kind", "classifier"), WATCHERS)
def test_direct_and_tail_streams_only_deliver_terminal_failure(
    tmp_path: Path, kind: str, classifier
) -> None:
    summary = (
        "Branch already merged"
        if kind == "merge"
        else "Pipeline complete for run run-20260923-001"
    )
    retry = (
        "Warning: transient merge status; retrying"
        if kind == "merge"
        else "GitHub Actions status relay is temporarily unavailable; retrying"
    )
    lines = [
        "ordinary progress 60 seconds no progress",
        retry,
        summary,
        "Error: nested command failed",
        "RuntimeError: nested command failed",
    ]
    raw = tmp_path / f"{kind}-failure.raw"
    progress = tmp_path / f"{kind}-failure.progress"
    _watch_capture_binding.stamp_writer(progress, kind)
    direct = io.StringIO()

    rc = _watch_runner.run_watcher(
        argv=[sys.executable, str(_child(tmp_path, lines, 7))],
        classifier=classifier,
        raw_capture=raw,
        progress_capture=progress,
        kind=kind,
        stdout_stream=direct,
        header_metadata=(
            "Self-deploy driver frozen at abc" if kind == "deploy" else None
        ),
        outcome_only=True,
    )
    delivered = io.StringIO()
    assert watch_tail.follow(progress, out=delivered, poll_interval=0.001) == 0

    raw_text = raw.read_text(encoding="utf-8")
    for line in lines:
        assert line in raw_text
    for user_stream in (direct.getvalue(), delivered.getvalue()):
        assert "Error: nested command failed" in user_stream
        assert "RuntimeError: nested command failed" in user_stream
        assert f"# watch_{kind} failure:" in user_stream
        assert "exit=7" in user_stream
        assert f"raw={raw}" in user_stream
        assert summary not in user_stream
        assert retry not in user_stream
        assert "ordinary progress" not in user_stream
        assert "writer_pid=" not in user_stream
        assert "Self-deploy driver frozen" not in user_stream
        assert f"# watch_{kind} exit=7" in user_stream
    assert rc == 7


def test_tail_keeps_ownership_markers_for_other_watchers(tmp_path: Path) -> None:
    progress = tmp_path / "pytest.progress"
    progress.write_text(
        _watch_capture_binding.writer_marker_line("pytest", pid=4242)
        + "# watch_pytest exit=0 raw=/tmp/pytest.raw\n",
        encoding="utf-8",
    )
    output = io.StringIO()

    assert watch_tail.follow(progress, out=output, poll_interval=0.001) == 0
    assert "writer_pid=4242" in output.getvalue()


@pytest.mark.parametrize(("kind", "classifier"), WATCHERS)
def test_success_summary_is_reported_only_after_zero_exit(
    tmp_path: Path, kind: str, classifier
) -> None:
    summary = (
        "Branch already merged"
        if kind == "merge"
        else "Pipeline complete for run run-20260923-002"
    )
    raw = tmp_path / f"{kind}-success.raw"
    progress = tmp_path / f"{kind}-success.progress"
    output = io.StringIO()
    rc = _watch_runner.run_watcher(
        argv=[
            sys.executable,
            str(_child(tmp_path, ["ordinary progress", summary], 0)),
        ],
        classifier=classifier,
        raw_capture=raw,
        progress_capture=progress,
        kind=kind,
        stdout_stream=output,
        outcome_only=True,
    )
    text = output.getvalue()

    assert rc == 0
    assert summary in raw.read_text(encoding="utf-8")
    assert "ordinary progress" not in text
    assert text.count(f"# watch_{kind} outcome:") == 1
    assert f"result: {summary}" in text
    assert "exit=0" in text
    assert f"# watch_{kind} exit=0" in text


def test_timeout_reports_cause_recovery_and_capture(tmp_path: Path) -> None:
    raw = tmp_path / "timeout.raw"
    progress = tmp_path / "timeout.progress"
    output = io.StringIO()
    rc = _watch_runner.run_watcher(
        argv=[sys.executable, "-c", "import time; time.sleep(5)"],
        classifier=lambda _line: Classification(LineClass.NOISE),
        raw_capture=raw,
        progress_capture=progress,
        kind="merge",
        stdout_stream=output,
        timeout_seconds=0.05,
        outcome_only=True,
    )
    text = output.getvalue()

    assert rc == _watch_runner.TIMEOUT_EXIT
    assert "timed out after 0.05 seconds" in text
    assert "recovery:" in text
    assert f"raw={raw}" in text
    assert f"# watch_merge exit={_watch_runner.TIMEOUT_EXIT}" in text


def test_undiagnosed_failure_names_unknown_cause_and_raw_capture(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "unknown.raw"
    progress = tmp_path / "unknown.progress"
    output = io.StringIO()
    rc = _watch_runner.run_watcher(
        argv=[
            sys.executable,
            str(_child(tmp_path, ["uncategorized failure detail"], 9)),
        ],
        classifier=lambda _line: Classification(LineClass.NOISE),
        raw_capture=raw,
        progress_capture=progress,
        kind="deploy",
        stdout_stream=output,
        outcome_only=True,
    )
    text = output.getvalue()

    assert rc == 9
    assert "terminal cause not diagnosed" in text
    assert "inspect the raw capture before retrying" in text
    assert "uncategorized failure detail" in raw.read_text(encoding="utf-8")
    assert f"exit={rc}" in text
    assert f"raw={raw}" in text


@pytest.mark.parametrize(
    "diagnostic",
    [
        "deploy driver source drift: the pinned source changed",
        "FAIL yoke_beta: could not copy: pg_dump failed",
        "receipt was not recorded; release gate will still refuse",
    ],
)
def test_deploy_terminal_diagnostics_are_preserved_as_the_final_cause(
    tmp_path: Path, diagnostic: str
) -> None:
    raw = tmp_path / "diagnostic.raw"
    raw.write_text(diagnostic + "\n", encoding="utf-8")

    outcome = format_terminal_outcome(kind="deploy", exit_code=2, raw_capture=raw)

    assert diagnostic in outcome
    assert "terminal cause not diagnosed" not in outcome


def test_specific_deploy_error_survives_later_generic_stage_failure(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "stage-failure.raw"
    terminal_error = (
        "Terminal error: FAILED ... PortabilityRefused ... Use a newly provisioned "
        "empty target or contact support"
    )
    raw.write_text(
        "\n".join(
            (
                "Step runner diagnostic: failed:failure",
                "Terminal failing job: candidate service suite",
                terminal_error,
                "Error: stage 'hosted-release' failed (exit code: 1)",
            )
        )
        + "\n",
        encoding="utf-8",
    )

    outcome = format_terminal_outcome(kind="deploy", exit_code=1, raw_capture=raw)

    assert terminal_error in outcome
    assert (
        "recovery: Use a newly provisioned empty target or contact support" in outcome
    )
    assert "Error: stage 'hosted-release' failed" not in outcome
    assert "exit=1" in outcome


def test_deadlock_abort_reports_named_cause_without_heartbeat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("YOKE_WATCH_QUIET_HEARTBEAT_SECONDS", "0.01")
    monkeypatch.setattr(
        gate_stall_report,
        "diagnose_quiet_run",
        lambda _pid: gate_stall_report.StallReport(
            waiting_on="own admission slot",
            reason=gate_stall_report.NESTED_ADMISSION_DEADLOCK,
            abort=True,
        ),
    )
    raw = tmp_path / "deadlock.raw"
    progress = tmp_path / "deadlock.progress"
    output = io.StringIO()
    rc = _watch_runner.run_watcher(
        argv=[sys.executable, "-c", "import time; time.sleep(5)"],
        classifier=lambda _line: Classification(LineClass.NOISE),
        raw_capture=raw,
        progress_capture=progress,
        kind="merge",
        stdout_stream=output,
        outcome_only=True,
    )
    text = output.getvalue()

    assert rc == _watch_runner.STALL_ABORT_EXIT
    assert "aborted: nested_admission_deadlock" in text
    assert "recovery:" in text
    assert "still running; waiting on" not in text
    assert f"# watch_merge exit={rc}" in text
    assert "nested_admission_deadlock" in raw.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("wait_mode", "expected"),
    [
        (WatchWaitMode("background-wake", "supported", "Monitor"), "Progress tail"),
        (WatchWaitMode("in-turn", "unsupported"), "Foreground command"),
    ],
)
def test_wait_mode_changes_transport_not_outcome_policy(wait_mode, expected) -> None:
    output = io.StringIO()
    _watch_runner.print_wait_mode_invocation(
        kind="merge",
        wrapper_module="yoke_core.tools.watch_merge",
        wrapper_args=["done-transition", "ITEM-1"],
        raw_capture=Path("/tmp/merge.raw"),
        progress_capture=Path("/tmp/merge.progress"),
        outcome_only=True,
        out=output,
        wait_mode=wait_mode,
    )
    text = output.getvalue()

    assert expected in text
    assert (
        "routine progress is suppressed" in text
        or "Routine progress is suppressed" in text
    )
    assert "raw capture" in text.lower()
    if wait_mode.waits_in_turn:
        assert "Progress tail" not in text
    else:
        assert "yoke watch tail" in text
