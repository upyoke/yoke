"""Standard harness probe retries, and the sanitized tail a timeout keeps."""

import json
import os
import subprocess
import tempfile
import sys
import shutil
import time
from types import SimpleNamespace

import pytest

from yoke_contracts.testing.real_home_isolation import set_home
from yoke_harness.baseline_harness_requests import read_rejection_record
from yoke_harness.baseline_probe_failure_causes import PROBE_EXIT_CODES
from yoke_harness.standard_baseline_probes import standard_probes
from yoke_harness.ssh_mac_baseline_probes import (
    parse_baseline_probes,
    run_baseline_probes,
)

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


@pytest.mark.posix_only(reason="runs on the POSIX test machine")
def test_an_exact_ok_with_one_tool_event_retries_and_then_passes(tmp_path):
    runs = _harness(tmp_path, "agent", [[SHELL_CALL, OK_RESULT], [OK_RESULT]])
    result = _run_probe(tmp_path, "Cursor")
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == ""
    assert runs.read_text() == "2"


@pytest.mark.posix_only(reason="runs on the POSIX test machine")
def test_a_steady_tool_call_fails_after_one_retry_and_names_the_tool(tmp_path):
    runs = _harness(tmp_path, "agent", [[SHELL_CALL, OK_RESULT]])
    result = _run_probe(tmp_path, "Cursor")
    assert result.returncode == PROBE_EXIT_CODES["probe_reply_unanswered"]
    assert runs.read_text() == "2"
    record = read_rejection_record(result.stdout)
    assert record is not None, result.stdout
    assert record["rejection"] == "tool_call_event"
    assert record["event_types"] == ["tool_call:shellToolCall", "result"]


@pytest.mark.posix_only(reason="runs on the POSIX test machine")
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


@pytest.mark.posix_only(reason="runs on the POSIX test machine")
def test_claude_tool_use_never_retries(tmp_path):
    tool_use = {"type": "assistant", "message": {"content": [{"type": "tool_use"}]}}
    runs = _harness(tmp_path, "claude", [[tool_use, OK_RESULT], [OK_RESULT]])
    result = _run_probe(tmp_path, "Claude")
    assert result.returncode == PROBE_EXIT_CODES["probe_reply_unanswered"]
    assert runs.read_text() == "1"


@pytest.mark.parametrize("second_stalls", [False, True])
def test_cursor_stall_retries_with_remaining_budget_and_retains_safe_evidence(
    monkeypatch, capsys, second_stalls
):
    now, timeouts = [100.0], []
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    monkeypatch.setattr(shutil, "which", lambda *a, **kw: "/usr/bin/agent")
    private = "private-account-and-reply"
    stream = (
        json.dumps({"type": "system", "content": private})
        + "\n"
        + json.dumps({"type": "assistant", "content": private})
        + "\n"
        + '{"type": "partial'
    ).encode()

    def run(argv, **kwargs):
        timeouts.append(kwargs["timeout"])
        assert kwargs["cwd"] == tempfile.gettempdir()
        if len(timeouts) == 1 or second_stalls:
            now[0] += kwargs["timeout"]
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"], output=stream)
        return SimpleNamespace(returncode=0, stdout=json.dumps(OK_RESULT), stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    probe = next(
        p for p in standard_probes("linux") if p["name"] == "Cursor real request"
    )
    with pytest.raises(SystemExit) as exit_info:
        exec(compile(probe["argv"][2], "cursor-probe", "exec"), {})
    assert timeouts == [50, 60]
    assert now[0] <= 210
    code = PROBE_EXIT_CODES["probe_request_timed_out"] if second_stalls else 0
    assert exit_info.value.code == code
    output, errors = capsys.readouterr()
    assert not errors and private not in output
    records = [json.loads(line) for line in output.splitlines()]
    assert len(records) == (2 if second_stalls else 1)
    assert all(
        r["event_count"] == 2 and r["event_types"] == ["assistant"] for r in records
    )
    assert read_rejection_record(output)["rejection"] == "probe_request_timed_out"
    if second_stalls:
        proven = run_baseline_probes(
            parse_baseline_probes(json.dumps({"probes": [probe]})),
            run_gui_command=lambda *a, **kw: SimpleNamespace(
                returncode=code, stdout=output, stderr=""
            ),
        )
        failure = proven.evidence["probes"][-1]
        assert failure["cause"] == "probe_request_timed_out"
        assert failure["reply_rejection"]["event_count"] == 2
        assert failure["reply_rejection"]["event_types"] == ["assistant"]


@pytest.mark.parametrize("name", ["Claude", "Codex"])
def test_other_harness_timeouts_keep_one_full_attempt_and_a_sanitized_tail(
    monkeypatch, capsys, name
):
    monkeypatch.setattr(time, "monotonic", lambda: 100)
    executable = "claude" if name == "Claude" else "codex"
    monkeypatch.setattr(shutil, "which", lambda *a, **kw: f"/usr/bin/{executable}")
    timeouts = []

    def run(argv, **kwargs):
        timeouts.append(kwargs["timeout"])
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"], output=b"private")

    monkeypatch.setattr(subprocess, "run", run)
    probe = next(
        p for p in standard_probes("linux") if p["name"] == f"{name} real request"
    )
    with pytest.raises(SystemExit) as exit_info:
        exec(compile(probe["argv"][2], "harness-probe", "exec"), {})
    assert exit_info.value.code == PROBE_EXIT_CODES["probe_request_timed_out"]
    assert timeouts == [110]
    output, errors = capsys.readouterr()
    assert not errors and "private" not in output
    record = read_rejection_record(output)
    assert record["harness"] == name
    assert record["rejection"] == "probe_request_timed_out"
    assert (record["event_count"], record["event_types"]) == (0, [])


@pytest.mark.posix_only(reason="runs on the POSIX test machine")
def test_a_codex_that_prints_then_hangs_leaves_a_sanitized_tail_on_the_receipt(
    tmp_path, monkeypatch, capsys
):
    secret = "sk-private-token-and-reply"
    events = [
        {"type": "thread.started", "thread_id": secret},
        {"type": "turn.started"},
        {"type": "error", "message": f"update required; token {secret}"},
    ]
    stream = "".join(json.dumps(event) + "\n" for event in events)
    codex = tmp_path / ".local/bin/codex"
    codex.parent.mkdir(parents=True)
    codex.write_text(
        f"#!{sys.executable}\n"
        "import sys, time\n"
        f"sys.stdout.write({stream!r})\n"
        "sys.stdout.flush()\n"
        "time.sleep(60)\n"
    )
    codex.chmod(0o700)
    set_home(monkeypatch, tmp_path)
    monkeypatch.setenv("PATH", "")
    # The probe's deadline starts 108 seconds spent, so the hang times out in 2.
    clock = iter([0.0])
    monkeypatch.setattr(time, "monotonic", lambda: next(clock, 108.0))
    probe = next(
        p for p in standard_probes("linux") if p["name"] == "Codex real request"
    )
    with pytest.raises(SystemExit) as exit_info:
        exec(compile(probe["argv"][2], "codex-probe", "exec"), {})
    code = exit_info.value.code
    assert code == PROBE_EXIT_CODES["probe_request_timed_out"]
    output, errors = capsys.readouterr()
    assert not errors and secret not in output
    proven = run_baseline_probes(
        parse_baseline_probes(json.dumps({"probes": [probe]})),
        run_gui_command=lambda *a, **kw: SimpleNamespace(
            returncode=code, stdout=output, stderr=""
        ),
    )
    failure = proven.evidence["probes"][-1]
    assert failure["cause"] == "probe_request_timed_out"
    assert failure["reply_rejection"]["harness"] == "Codex"
    assert failure["reply_rejection"]["event_count"] == 3
    assert failure["reply_rejection"]["event_types"] == ["error"]
    assert "Codex reply rejected at `probe_request_timed_out`" in failure["reason"]
    assert secret not in json.dumps(proven.evidence)


@pytest.mark.parametrize(
    "output", [None, b"", "not json\n{}\n", b'{"type":"secret / reply"}\n']
)
def test_timeout_diagnostics_sanitize_empty_and_unrecognized_events(output):
    from yoke_harness.baseline_harness_requests import harness_request

    record = harness_request(["agent"]).timeout_rejection(output)
    assert record["event_count"] == (0 if not output else 1)
    assert record["event_types"] == (
        [] if not output else [None if isinstance(output, str) else "<other>"]
    )


@pytest.mark.posix_only(reason="runs on the POSIX test machine")
def test_a_codex_that_waits_for_stdin_eof_answers_when_stdin_stays_open(tmp_path):
    """Over SSH the probe's stdin stays open; codex exec waits for its EOF."""
    codex = tmp_path / ".local/bin/codex"
    codex.parent.mkdir(parents=True)
    reply = [{"type": "turn.started"}, {"type": "item.completed", "item": {"type": "agent_message", "text": "OK"}}, {"type": "turn.completed"}]
    stream = "".join(json.dumps(event) + "\n" for event in reply)
    codex.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        "sys.stdin.read()\n"
        f"sys.stdout.write({stream!r})\n"
    )
    codex.chmod(0o700)
    probe = next(
        p for p in standard_probes("linux") if p["name"] == "Codex real request"
    )
    read_end, write_end = os.pipe()
    try:
        result = subprocess.run(
            probe["argv"],
            env={**os.environ, "HOME": str(tmp_path), "PATH": str(tmp_path / ".local/bin")},
            stdin=read_end,
            capture_output=True,
            text=True,
            timeout=30,
        )
    finally:
        os.close(read_end)
        os.close(write_end)
    assert result.returncode == 0, result.stdout + result.stderr
