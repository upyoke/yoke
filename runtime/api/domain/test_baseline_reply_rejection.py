"""The shared reply parser describes a rejected harness reply without its text."""

from __future__ import annotations

import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from runtime.api.domain.baseline_harness_requests_test_support import (
    _Control,
    _events,
    _response,
)
from yoke_harness.baseline_harness_requests import harness_request
from yoke_harness.ssh_linux_baseline import prove_linux_probes
from yoke_harness.ssh_mac_baseline_probes import (
    parse_baseline_probes,
    run_baseline_probes,
)
from yoke_harness.standard_baseline_probes import standard_probes


@pytest.mark.parametrize("program", ["claude", "codex", "cursor-agent"])
def test_an_accepted_reply_leaves_no_rejection_record(program):
    assert (
        harness_request([f"/bin/{program}"]).reply_rejection(_response(program)) is None
    )


_SECRET = "private-account@example.com sk-live-123"


@pytest.mark.parametrize(
    "stdout,branch,flags",
    [
        ("", "no_events", (False, False, False)),
        ("oops " + _SECRET, "malformed_stream", (False, False, True)),
        (
            _events(
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "tool_use", "input": _SECRET}]},
                }
            ),
            "assistant_tool_use",
            (False, True, False),
        ),
        (
            _events(
                {"type": "system", "subtype": "init", "session_id": _SECRET},
                {"type": "result", "subtype": "success", "result": _SECRET},
            ),
            "reply_not_exact",
            (False, False, False),
        ),
        (
            _events(
                {
                    "type": "result",
                    "subtype": "error_during_execution",
                    "is_error": True,
                    "result": "OK",
                }
            ),
            "result_error",
            (True, False, False),
        ),
        (
            _events({"type": "assistant", "message": {"content": []}}),
            "no_completion_event",
            (False, False, False),
        ),
    ],
)
def test_a_rejected_reply_names_its_branch_without_reply_text(stdout, branch, flags):
    request = harness_request(["/bin/agent"])
    record = request.reply_rejection(stdout)
    assert record["harness"] == "Cursor"
    assert record["rejection"] == branch
    assert (
        record["exact_ok_reply"],
        record["tool_use"],
        record["degraded_context"],
    ) == flags
    assert record["event_count"] == len(
        [line for line in stdout.splitlines() if line.strip()]
    )
    assert len(record["event_types"]) == record["event_count"]
    assert "private-account" not in json.dumps(record)
    assert "sk-live" not in json.dumps(record)


def test_cursor_read_only_tools_keep_tool_use_when_the_reply_is_not_ok():
    stdout = _events(
        {
            "type": "tool_call",
            "subtype": "completed",
            "tool_call": {"lsToolCall": {"args": {"path": "/tmp"}}},
        },
        {"type": "result", "subtype": "success", "result": "Hello"},
    )
    record = harness_request(["/bin/agent"]).reply_rejection(stdout)
    assert record["rejection"] == "reply_not_exact"
    assert record["tool_use"] is True
    assert record["exact_ok_reply"] is False


def test_a_bare_cursor_tool_call_still_rejects():
    stdout = _events(
        {"type": "tool_call", "subtype": "started"},
        {"type": "result", "subtype": "success", "result": "OK"},
    )
    record = harness_request(["/bin/cursor-agent"]).reply_rejection(stdout)
    assert record["rejection"] == "tool_call_event"
    assert record["tool_use"] is True


def test_a_declared_harness_probe_keeps_its_rejection_on_the_failed_row():
    stdout = _events(
        {"type": "result", "subtype": "success", "result": "Hello " + _SECRET}
    )
    control = _Control("cursor-agent", stdout=stdout)
    result = prove_linux_probes(control, control.document)
    row = result.evidence["probes"][0]
    assert row["reply_rejection"]["rejection"] == "reply_not_exact"
    assert row["reply_rejection"]["harness_exit_code"] == 0
    assert row["reply_rejection"]["event_types"] == ["result"]
    assert "`reply_not_exact`" in result.evidence["reason"]
    assert "private-account" not in repr(result.evidence)


@pytest.mark.parametrize(
    "ending,answer,rejection",
    [
        ("turn.completed", "OK", None),
        ("turn.failed", "OK", "turn_failed_event"),
        (None, "OK", "no_completion_event"),
        ("turn.completed", "Wrong reply", "reply_not_exact"),
    ],
)
@pytest.mark.parametrize("sealed", [False, True])
def test_codex_records_stream_errors_and_requires_an_exact_completed_reply(
    ending, answer, rejection, sealed, monkeypatch, capsys
):
    events = [
        {"type": "error", "message": _SECRET},
        {"type": "error", "message": _SECRET},
        {"type": "item.completed", "item": {"type": "agent_message", "text": answer}},
    ]
    if ending:
        events.append({"type": ending})
    native_result = SimpleNamespace(returncode=0, stdout=_events(*events), stderr="")
    if sealed:
        probe = next(
            p for p in standard_probes("windows") if p["name"] == "Codex real request"
        )
        monkeypatch.setattr(shutil, "which", lambda *args, **kwargs: "/bin/codex")
        monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: native_result)
        with pytest.raises(SystemExit) as exited:
            exec(compile(probe["argv"][2], "codex-probe", "exec"), {})
        result = SimpleNamespace(
            returncode=exited.value.code, stdout=capsys.readouterr().out, stderr=""
        )
    else:
        probe = {"name": "signed-in Codex", "argv": ["/bin/codex"]}
        result = native_result

    probes = parse_baseline_probes(json.dumps({"probes": [probe]}))
    receipt = run_baseline_probes(
        probes, run_gui_command=lambda *args, **kwargs: result
    )
    row = receipt.evidence["probes"][0]
    assert receipt.ok is (rejection is None)
    if rejection:
        assert row["reply_rejection"]["rejection"] == rejection
        assert row["reply_rejection"]["error_event_count"] == 2
    else:
        assert row["error_event_count"] == 2
    assert _SECRET not in repr(receipt.evidence)
