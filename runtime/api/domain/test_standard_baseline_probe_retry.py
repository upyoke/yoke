"""A Cursor probe whose only fault is one tool call retries once."""

import json
import os
import subprocess
import sys

import pytest

from yoke_harness.baseline_harness_requests import read_rejection_record
from yoke_harness.baseline_probe_failure_causes import PROBE_EXIT_CODES
from yoke_harness.standard_baseline_probes import standard_probes

OK_RESULT = {"type": "result", "subtype": "success", "is_error": False, "result": "OK"}
SHELL_CALL = {
    "type": "tool_call",
    "subtype": "started",
    "tool_call": {"shellToolCall": {"args": {"command": "ls"}}},
}


def _harness(tmp_path, executable, replies):
    """Install a fake harness that prints one scripted reply per run."""
    path = tmp_path / ".local/bin" / executable
    path.parent.mkdir(parents=True)
    runs = tmp_path / "runs"
    streams = ["\n".join(json.dumps(event) for event in reply) for reply in replies]
    path.write_text(
        f"#!{sys.executable}\n"
        "import pathlib\n"
        f"runs = pathlib.Path({str(runs)!r})\n"
        "count = int(runs.read_text()) if runs.exists() else 0\n"
        "runs.write_text(str(count + 1))\n"
        f"streams = {streams!r}\n"
        "print(streams[min(count, len(streams) - 1)])\n"
    )
    path.chmod(0o700)
    return runs


def _run_probe(tmp_path, name):
    probe = next(
        p for p in standard_probes("linux") if p["name"] == f"{name} real request"
    )
    return subprocess.run(
        probe["argv"],
        env={**os.environ, "HOME": str(tmp_path), "PATH": str(tmp_path / ".local/bin")},
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_an_exact_ok_with_one_tool_event_retries_and_then_passes(tmp_path):
    runs = _harness(tmp_path, "agent", [[SHELL_CALL, OK_RESULT], [OK_RESULT]])
    result = _run_probe(tmp_path, "Cursor")
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == ""
    assert runs.read_text() == "2"


def test_a_steady_tool_call_fails_after_one_retry_and_names_the_tool(tmp_path):
    runs = _harness(tmp_path, "agent", [[SHELL_CALL, OK_RESULT]])
    result = _run_probe(tmp_path, "Cursor")
    assert result.returncode == PROBE_EXIT_CODES["probe_reply_unanswered"]
    assert runs.read_text() == "2"
    record = read_rejection_record(result.stdout)
    assert record is not None, result.stdout
    assert record["rejection"] == "tool_call_event"
    assert record["event_types"] == ["tool_call:shellToolCall", "result"]


@pytest.mark.parametrize(
    "reply",
    [
        # The reply is not exactly OK, so the tool call is not the only fault.
        [SHELL_CALL, {**OK_RESULT, "result": "Done"}],
        # The run itself failed.
        [SHELL_CALL, {**OK_RESULT, "subtype": "error", "is_error": True}],
    ],
)
def test_a_tool_call_with_another_fault_does_not_retry(tmp_path, reply):
    runs = _harness(tmp_path, "agent", [reply])
    result = _run_probe(tmp_path, "Cursor")
    assert result.returncode == PROBE_EXIT_CODES["probe_reply_unanswered"]
    assert runs.read_text() == "1"


def test_claude_tool_use_never_retries(tmp_path):
    tool_use = {"type": "assistant", "message": {"content": [{"type": "tool_use"}]}}
    runs = _harness(tmp_path, "claude", [[tool_use, OK_RESULT], [OK_RESULT]])
    result = _run_probe(tmp_path, "Claude")
    assert result.returncode == PROBE_EXIT_CODES["probe_reply_unanswered"]
    assert runs.read_text() == "1"
