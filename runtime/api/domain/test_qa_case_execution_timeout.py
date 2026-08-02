"""Timeout tests for admission-gated Command QA cases."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from yoke_core.domain import (
    qa_case_command_stream,
    qa_case_execution,
    qa_case_execution_cli,
    test_gate_timeout,
)


WATCHED_COMMAND = (
    "uv run --frozen python3 -m yoke_core.tools.watch_pytest -- runtime/api/"
)


def _case() -> dict:
    return {
        "requirement_id": 41,
        "item_id": 9,
        "case_key": "quick",
        "project": "yoke",
        "method_config": {"command": WATCHED_COMMAND},
    }


def _execute(
    tmp_path: Path,
    streamed: qa_case_command_stream.StreamedCommand,
    *,
    timeout_seconds: int = 17,
) -> tuple[dict, dict]:
    """Run one Command case over a canned stream result.

    Returns the execution result and everything the stubbed collaborators
    saw: the ``stream_command`` kwargs plus each dispatched payload.
    """
    captured: dict[str, object] = {}

    def run_command(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return streamed

    def dispatch(function_id, _requirement_id, payload, **_kwargs):
        captured[function_id] = payload
        return {
            "qa.run.add": {"qa_run_id": 1},
            "qa.artifact.add": {"qa_artifact_id": 2},
            "qa.run.complete": {"qa_run_id": 1},
        }[function_id]

    with (
        mock.patch.object(
            qa_case_command_stream,
            "stream_command",
            side_effect=run_command,
        ),
        mock.patch.object(qa_case_execution, "_dispatch", side_effect=dispatch),
    ):
        result = qa_case_execution._command_result(
            _case(),
            timeout_seconds=timeout_seconds,
            checkout_path=tmp_path,
        )
    return result, captured


def _timed_out(tmp_path: Path, output: str) -> qa_case_command_stream.StreamedCommand:
    return qa_case_command_stream.StreamedCommand(
        exit_code=124,
        timed_out=True,
        output=output,
        capture_path=tmp_path / "capture.log",
    )


def test_watched_command_starts_its_budget_after_gate_admission(
    tmp_path: Path,
) -> None:
    result, captured = _execute(tmp_path, _timed_out(tmp_path, "timed out"))

    assert result["verdict"] == "fail"
    # No parent deadline: the watched run counts its own budget from the
    # moment the gate admits it, not from when it started queueing.
    assert captured["timeout_seconds"] is None
    assert captured["env"][test_gate_timeout.WATCH_EXECUTION_TIMEOUT_ENV] == "17"
    assert json.loads(captured["qa.artifact.add"]["metadata"])["timed_out"] is True


def test_timed_out_record_names_the_queue_wait_it_was_not_charged(
    tmp_path: Path,
) -> None:
    output = (
        f"{test_gate_timeout.SLOT_ACQUIRED_PREFIX}932s\n"
        "10 workers [20643 items]\n"
        "# watch_pytest timed out after 17 seconds; child process group reaped\n"
    )

    result, captured = _execute(tmp_path, _timed_out(tmp_path, output))

    summary = result["timeout_summary"]
    assert "timed out after 17s of execution" in summary
    assert "932s" in summary
    assert "not failing tests" in summary
    # The durable record carries it too, not just the returned dict.
    record = json.loads(captured["qa.run.complete"]["raw_result"])
    assert record["timeout_summary"] == summary
    assert summary in record["output_tail"]


def test_timed_out_record_omits_a_queue_wait_that_never_happened(
    tmp_path: Path,
) -> None:
    result, _ = _execute(tmp_path, _timed_out(tmp_path, "10 workers\n"))

    assert result["timeout_summary"].startswith("timed out after 17s of execution;")


def test_passing_run_records_no_timeout_summary(tmp_path: Path) -> None:
    passed = qa_case_command_stream.StreamedCommand(
        exit_code=0,
        timed_out=False,
        output=f"{test_gate_timeout.SLOT_ACQUIRED_PREFIX}932s\n",
        capture_path=tmp_path / "capture.log",
    )

    result, captured = _execute(tmp_path, passed)

    assert result["verdict"] == "pass"
    assert result["timeout_summary"] == ""
    assert "timeout_summary" not in json.loads(
        captured["qa.run.complete"]["raw_result"]
    )


def test_cli_restates_a_timeout_alongside_the_failing_verdict(
    capsys,
    monkeypatch,
) -> None:
    summary = test_gate_timeout.timeout_summary(1200, 932.0)
    monkeypatch.setattr(
        qa_case_execution_cli,
        "execute_case",
        lambda *_a, **_k: {
            "verdict": "fail",
            "case_outcome": "failed",
            "exit_code": 124,
            "timed_out": True,
            "timeout_summary": summary,
        },
    )
    monkeypatch.setattr(
        "yoke_core.api.service_client_structured_api_adapter.build_actor",
        lambda session_id=None: None,
    )

    exit_code = qa_case_execution_cli.run(["--requirement-id", "41"])

    assert exit_code == 1
    assert summary in capsys.readouterr().err


def test_unwatched_command_keeps_its_parent_timeout() -> None:
    env: dict[str, str] = {}

    timeout = test_gate_timeout.process_timeout_for_command(
        "ruff check package", 17, env
    )

    assert timeout == 17
    assert env == {}
