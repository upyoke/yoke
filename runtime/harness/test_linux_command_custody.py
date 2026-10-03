"""Transport timeout is settled only by the matching remote custody receipt."""

import json
import shlex
import subprocess
from types import SimpleNamespace

import pytest

from yoke_harness import linux_command_custody as custody


@pytest.mark.parametrize("transport", ["completed", "timeout", "dropped"])
def test_remote_receipt_settles_output_and_deadline(transport):
    calls = []
    receipt = None

    def run(command, **kw):
        nonlocal receipt
        calls.append((command, kw))
        tokens = shlex.split(command)
        if len(calls) == 1:
            directory, argv, environment, timeout = map(json.loads, tokens[-4:])
            assert argv == ["xdotool", "key", "Return"]
            assert environment == {"DISPLAY": ":10"}
            assert timeout < kw["timeout"]
            receipt = {
                "command_id": directory.rsplit("/", 1)[-1],
                "termination_verified": True,
                "returncode": 0 if transport == "completed" else 124,
            }
            stderr = "diagnostic\n"
            if transport == "completed":
                stderr += (
                    custody.remote.HEARTBEAT
                    + custody.remote.RECEIPT_MARKER
                    + json.dumps(receipt)
                    + "\n"
                )
            return subprocess.CompletedProcess(
                [],
                {"completed": 0, "timeout": 124, "dropped": 255}[transport],
                "partial",
                stderr,
            )
        if "print(json.dumps(read_result" in tokens[2]:
            return subprocess.CompletedProcess(
                [],
                0,
                json.dumps(
                    {"receipt": receipt, "stdout": "complete", "stderr": "diagnostic\n"}
                ),
                "",
            )
        return subprocess.CompletedProcess([], 0, "", "")

    result = custody.run_command(
        SimpleNamespace(_run=run),
        ["xdotool", "key", "Return"],
        {"DISPLAY": ":10"},
        timeout=1,
    )
    assert result.returncode == (0 if transport == "completed" else 124)
    assert result.stdout == ("partial" if transport == "completed" else "complete")
    assert result.command_custody["termination_verified"] is True
    assert "YOKE_COMMAND_" not in result.stderr


@pytest.mark.parametrize(
    "receipt",
    [
        None,
        {"termination_verified": False},
        {"command_id": "another-command", "termination_verified": True},
    ],
)
def test_uncertain_remote_custody_is_explicit_and_keeps_recovery_handle(receipt):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(
            [],
            124 if len(calls) == 1 else 0,
            "" if len(calls) == 1 else json.dumps({"receipt": receipt}),
            "ssh lost\n",
        )

    result = custody.run_command(SimpleNamespace(_run=run), ["true"], {}, timeout=1)
    assert result.returncode == 69
    assert "linux_command_custody_unsettled: /tmp/yoke-command-" in result.stderr
    assert len(calls) == 2  # No cleanup of unverified custody.


@pytest.mark.parametrize(
    "reason,code,accepted",
    [
        ("completed", 0, True),
        ("completed", 3, False),
        ("deadline", 0, False),
        ("ssh_disconnected", 0, False),
    ],
)
def test_persistent_children_are_released_only_after_verified_normal_exit(
    reason, code, accepted
):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if len(calls) == 1:
            directory = json.loads(shlex.split(command)[-4])
            receipt = {
                "command_id": directory.rsplit("/", 1)[-1],
                "reason": reason,
                "returncode": code,
                "completion_verified": True,
                "termination_verified": False,
                "released_pids": [123],
            }
            return subprocess.CompletedProcess(
                [], 0, "", custody.remote.RECEIPT_MARKER + json.dumps(receipt) + "\n"
            )
        return subprocess.CompletedProcess([], 0, "", "")

    result = custody.run_command(
        SimpleNamespace(_run=run), ["browser", "start"], {}, timeout=1
    )
    assert result.returncode == (0 if accepted else 69)
    assert len(calls) == (2 if accepted else 1)
