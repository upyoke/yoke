"""Timeout tests for admission-gated Command QA cases."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from yoke_core.domain import (
    qa_case_command_stream,
    qa_case_execution,
    test_gate_timeout,
)


def test_watched_command_starts_its_budget_after_gate_admission(
    tmp_path: Path,
) -> None:
    case = {
        "requirement_id": 41,
        "item_id": 9,
        "case_key": "quick",
        "project": "yoke",
        "method_config": {
            "command": (
                "uv run --frozen python3 -m yoke_core.tools.watch_pytest "
                "-- runtime/api/"
            )
        },
    }
    captured: dict[str, object] = {}

    def run_command(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return qa_case_command_stream.StreamedCommand(
            exit_code=124,
            timed_out=True,
            output="timed out",
            capture_path=tmp_path / "capture.log",
        )

    def dispatch(function_id, _requirement_id, payload, **_kwargs):
        if function_id == "qa.artifact.add":
            captured["artifact_payload"] = payload
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
            case,
            timeout_seconds=17,
            checkout_path=tmp_path,
        )

    assert result["verdict"] == "fail"
    # No parent deadline: the watched run counts its own budget from the
    # moment the gate admits it, not from when it started queueing.
    assert captured["timeout_seconds"] is None
    assert captured["env"][test_gate_timeout.WATCH_EXECUTION_TIMEOUT_ENV] == "17"
    assert json.loads(captured["artifact_payload"]["metadata"])["timed_out"] is True


def test_unwatched_command_keeps_its_parent_timeout() -> None:
    env: dict[str, str] = {}

    timeout = test_gate_timeout.process_timeout_for_command(
        "ruff check package", 17, env
    )

    assert timeout == 17
    assert env == {}
