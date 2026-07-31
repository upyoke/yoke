"""Tests that a timed-out QA registered command reaps its process tree.

Split from the shared QA case-execution tests so each file stays within
the authored-file line limit. A registered command runs through a shell,
so the work it starts is a grandchild; killing only the shell would
leave a test run alive holding its databases open.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock
import os
import time

import pytest

from yoke_core.domain import qa_case_execution

from runtime.api.domain.test_qa_case_execution import _case


def test_command_case_timeout_reaps_the_whole_process_tree(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A timed-out registered command must not leave work running.

    The command runs through a shell, so a test run it starts is a
    grandchild. Killing only the shell would leave that run alive holding its
    databases open, wedging the cluster for everyone else.
    """
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
    pid_file = tmp_path / "grandchild.pid"
    case = _case(
        "command",
        "worktree_run",
        {
            "command": f"sleep 300 & echo $! > {pid_file}; sleep 300",
            "timeout_seconds": 1,
        },
    )

    def dispatch(function_id, requirement_id, payload, *, actor=None):
        if function_id == "qa.run.add":
            return {"qa_run_id": 77}
        if function_id == "qa.artifact.add":
            return {"qa_artifact_id": 88}
        if function_id == "qa.run.complete":
            return {"qa_run_id": 77}
        raise AssertionError(function_id)

    with (
        mock.patch.object(
            qa_case_execution, "fetch_case_execution_context", return_value=case
        ),
        mock.patch.object(
            qa_case_execution, "_execution_checkout", return_value=tmp_path
        ),
        mock.patch.object(qa_case_execution, "_dispatch", side_effect=dispatch),
    ):
        result = qa_case_execution.execute_case(41, timeout_seconds=1)

    assert result["verdict"] == "fail"
    grandchild_pid = int(pid_file.read_text().strip())
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            os.kill(grandchild_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    with pytest.raises(ProcessLookupError):
        os.kill(grandchild_pid, 0)
