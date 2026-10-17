"""A failed reset keeps its first error and the evidence of every failed call."""

from __future__ import annotations

import shlex
from types import SimpleNamespace

from runtime.api.domain.ssh_mac_full_reset_test_support import (
    GOLDEN_BASELINE_PATH,
    closed_reset_stdout,
)
from yoke_harness.ssh_mac_full_reset import (
    TEST_MAC_RESET_ADAPTER_FAILED,
    TEST_MAC_RESET_TRANSPORT_FAILED,
    execute_full_test_machine_reset,
)
from yoke_harness.ssh_mac_full_reset_contract import FULL_RESET_REMOTE_PATH
from yoke_harness.ssh_test_machine_transport import TRANSPORT_FAILURE_EXIT

HOME = "/Users/tester"
UNAVAILABLE = "host_control subprocess unavailable: OSError: [Errno 24] Too many"


def _call_name(command: str) -> str:
    argv = shlex.split(command)
    if argv[0] == FULL_RESET_REMOTE_PATH:
        return "reset"
    return "mode" if argv[0] == "/bin/chmod" else "rm"


class ScriptedHost:
    """Answer each reset call from a script; rm answers preclean, then cleanup."""

    def __init__(self, **answers) -> None:
        self.answers = answers
        self.rm_calls = 0
        self.upload_error: Exception | None = None

    def upload(self, path: str, content: str) -> None:
        if self.upload_error is not None:
            raise self.upload_error

    def run(self, command: str, *, timeout: int = 60):
        name = _call_name(command)
        if name == "rm":
            self.rm_calls += 1
            name = "preclean" if self.rm_calls == 1 else "cleanup"
        answer = self.answers.get(name)
        if isinstance(answer, Exception):
            raise answer
        if answer is None:
            stdout = closed_reset_stdout() if name == "reset" else ""
            return SimpleNamespace(returncode=0, stdout=stdout, stderr="")
        return SimpleNamespace(returncode=answer[0], stdout="", stderr=answer[1])


def _reset(host: ScriptedHost):
    return execute_full_test_machine_reset(
        run_remote=host.run,
        upload_text=host.upload,
        home=HOME,
        golden_baseline_path=GOLDEN_BASELINE_PATH,
    )


def _cleanup_outcome(result) -> str:
    return result.evidence["paths"][2]["outcome"]


def test_first_error_survives_a_later_cleanup_failure() -> None:
    host = ScriptedHost(
        preclean=(1, "rm: Operation not permitted"),
        cleanup=(TRANSPORT_FAILURE_EXIT, UNAVAILABLE),
    )

    result = _reset(host)

    assert not result.ok
    assert result.error_code == "test_mac_reset_script_preclean_failed"
    assert _cleanup_outcome(result) == "cleanup-failed"
    assert result.evidence["failed_calls"] == [
        {"call": "preclean", "exit_code": 1, "stderr": "rm: Operation not permitted"},
        {"call": "cleanup", "exit_code": TRANSPORT_FAILURE_EXIT, "stderr": UNAVAILABLE},
    ]


def test_transport_exit_on_the_reset_program_is_named_as_transport() -> None:
    host = ScriptedHost(reset=(TRANSPORT_FAILURE_EXIT, UNAVAILABLE))

    result = _reset(host)

    # A runner-side stop is not a reset phase failure; the host may be fine.
    assert result.error_code == TEST_MAC_RESET_TRANSPORT_FAILED
    assert "reset_phase" not in result.evidence
    assert result.evidence["failed_calls"] == [
        {"call": "reset", "exit_code": TRANSPORT_FAILURE_EXIT, "stderr": UNAVAILABLE}
    ]
    assert _cleanup_outcome(result) == "removed"


def test_transport_exit_on_cleanup_after_a_clean_restore_is_named() -> None:
    host = ScriptedHost(cleanup=(TRANSPORT_FAILURE_EXIT, UNAVAILABLE))

    result = _reset(host)

    assert not result.ok
    assert result.error_code == TEST_MAC_RESET_TRANSPORT_FAILED
    assert _cleanup_outcome(result) == "cleanup-failed"


def test_an_upload_exception_is_kept_with_its_type_and_message() -> None:
    host = ScriptedHost()
    host.upload_error = RuntimeError("Host-control text upload failed")

    result = _reset(host)

    assert result.error_code == TEST_MAC_RESET_ADAPTER_FAILED
    assert result.evidence["failed_calls"] == [
        {
            "call": "upload",
            "exception_type": "RuntimeError",
            "exception": "Host-control text upload failed",
        }
    ]
    assert _cleanup_outcome(result) == "removed"


def test_a_raising_cleanup_does_not_replace_the_mode_failure() -> None:
    host = ScriptedHost(
        mode=(1, "chmod: Permission denied"),
        cleanup=OSError("connection reset"),
    )

    result = _reset(host)

    assert result.error_code == "test_mac_reset_script_mode_failed"
    assert [call["call"] for call in result.evidence["failed_calls"]] == [
        "mode",
        "cleanup",
    ]
    assert result.evidence["failed_calls"][1]["exception_type"] == "OSError"
    assert _cleanup_outcome(result) == "cleanup-failed"


def test_a_clean_reset_records_no_failed_calls() -> None:
    result = _reset(ScriptedHost())

    assert result.ok
    assert "failed_calls" not in result.evidence
