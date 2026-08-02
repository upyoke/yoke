"""A registered Command case must be watchable while it runs.

Split from the shared QA case-execution tests so each file stays within
the authored-file line limit. This run IS the verification gate, so an
agent has to be able to follow it live and re-read it afterwards; when it
could only be read after the fact, agents ran the same suite by hand
first and the machine paid for the identical work twice.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest import mock

from yoke_core.domain import (
    qa_case_command_stream,
    qa_case_execution,
    qa_case_execution_cli,
)

from runtime.api.domain.test_qa_case_execution import _case


def _recording_dispatch(calls: list):
    def dispatch(function_id, requirement_id, payload, *, actor=None):
        calls.append((function_id, payload))
        if function_id == "qa.artifact.add":
            return {"qa_artifact_id": 88}
        if function_id in ("qa.run.add", "qa.run.complete"):
            return {"qa_run_id": 77}
        raise AssertionError(function_id)

    return dispatch


def _execute(case: dict, tmp_path: Path, calls: list, **kwargs) -> dict:
    with (
        mock.patch.object(
            qa_case_execution,
            "fetch_case_execution_context",
            return_value=case,
        ),
        mock.patch.object(
            qa_case_execution, "_execution_checkout", return_value=tmp_path
        ),
        mock.patch.object(
            qa_case_execution, "_dispatch", side_effect=_recording_dispatch(calls)
        ),
    ):
        return qa_case_execution.execute_case(41, **kwargs)


def test_command_case_streams_output_and_reports_its_capture(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
    relayed = io.StringIO()
    real_stream_command = qa_case_command_stream.stream_command
    monkeypatch.setattr(
        qa_case_command_stream,
        "stream_command",
        lambda command, **kwargs: real_stream_command(
            command, stream=relayed, **kwargs
        ),
    )
    case = _case("command", "worktree_run", {"command": "echo streamed-line"})
    calls: list = []

    result = _execute(case, tmp_path, calls)

    assert result["verdict"] == "pass"
    # Live relay: the line reached the caller's stream during the run, not
    # only the artifact written after it finished.
    assert "streamed-line" in relayed.getvalue()
    capture = Path(result["output_capture"])
    assert capture.is_file()
    assert "streamed-line" in capture.read_text(encoding="utf-8")


def test_command_case_capture_survives_a_failing_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
    case = _case(
        "command",
        "worktree_run",
        {"command": "echo why-it-failed; exit 3"},
    )
    calls: list = []

    result = _execute(case, tmp_path, calls)

    assert result["verdict"] == "fail"
    assert result["exit_code"] == 3
    capture_text = Path(result["output_capture"]).read_text(encoding="utf-8")
    assert "why-it-failed" in capture_text
    raw_result = json.loads(dict(calls)["qa.run.complete"]["raw_result"])
    assert raw_result["exit_code"] == 3
    assert raw_result["timed_out"] is False
    assert "why-it-failed" in raw_result["output_tail"]


def test_cli_restates_the_verdict_and_capture_on_stderr(
    capsys,
    monkeypatch,
) -> None:
    outcome = {
        "verdict": "fail",
        "case_outcome": "failed",
        "exit_code": 3,
        "output_capture": "/scratch/watcher-captures/qa_case.raw.log",
    }
    monkeypatch.setattr(
        qa_case_execution_cli, "execute_case", lambda *a, **k: outcome
    )
    monkeypatch.setattr(
        "yoke_core.api.service_client_structured_api_adapter.build_actor",
        lambda session_id=None: None,
    )

    exit_code = qa_case_execution_cli.run(["--requirement-id", "41"])

    captured = capsys.readouterr()
    assert exit_code == 1
    # stdout stays machine-readable; the human-facing restatement is stderr.
    assert json.loads(captured.out)["verdict"] == "fail"
    assert "verdict=fail" in captured.err
    assert "exit_code=3" in captured.err
    assert "capture=/scratch/watcher-captures/qa_case.raw.log" in captured.err
