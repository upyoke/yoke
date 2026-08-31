"""Stalled pending-run diagnostics for the QA-case watcher."""

from __future__ import annotations

import io
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from yoke_core.domain.github_actions_run_stall import (
    PENDING_ZERO_JOBS_STALL_SECONDS,
    PENDING_ZERO_JOBS_STALL_REASON,
    pending_run_message,
)
from yoke_core.tools import _watch_runner, watch_progress_stall, watch_qa_case
from yoke_core.tools._watch_throttle import LineClass


def _stalled_line() -> str:
    observed = datetime(2026, 8, 31, 12, tzinfo=timezone.utc)
    updated = observed - timedelta(seconds=PENDING_ZERO_JOBS_STALL_SECONDS + 1)
    message = pending_run_message(
        repo="upyoke/yoke",
        run_id="88",
        jobs_count=0,
        updated_at=updated.isoformat(),
        observed_at=observed,
    )
    return f"  Workflow status: {message}\n"


def test_pending_zero_jobs_stall_is_urgent_with_force_cancel_recovery() -> None:
    line = _stalled_line()

    classification = watch_qa_case.QaCaseLineClassifier()(line)

    assert classification.cls is LineClass.URGENT
    assert f"waiting_on={PENDING_ZERO_JOBS_STALL_REASON}" in line
    assert "actions/runs/88/force-cancel" in line


def test_named_stall_does_not_fall_back_to_progress_throttle(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        watch_progress_stall.PROGRESS_STALL_SECONDS_ENV,
        "0.04",
    )
    monkeypatch.setenv(_watch_runner.QUIET_HEARTBEAT_SECONDS_ENV, "30")
    line = _stalled_line().rstrip()
    script = tmp_path / "stalled_run.py"
    script.write_text(
        "import time\n"
        f"line = {line!r}\n"
        "for _ in range(12):\n"
        "    print(line, flush=True)\n"
        "    time.sleep(0.01)\n",
        encoding="utf-8",
    )
    progress = tmp_path / "progress.log"

    rc = _watch_runner.run_watcher(
        argv=[sys.executable, str(script)],
        classifier=watch_qa_case.QaCaseLineClassifier(),
        raw_capture=tmp_path / "raw.log",
        progress_capture=progress,
        kind=watch_qa_case.KIND,
        stdout_stream=io.StringIO(),
    )

    assert rc == 0
    text = progress.read_text(encoding="utf-8")
    assert f"waiting_on={PENDING_ZERO_JOBS_STALL_REASON}" in text
    assert "waiting_on=progress_throttle" not in text
