"""A raised baseline probe call keeps its typed cause, never its raw text."""

import json
from types import SimpleNamespace

import pytest

from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_harness.baseline_probe_provider_stall import NO_VERDICT_ERROR_CODE
from yoke_harness.native_windows.probes import prove_document
from yoke_harness.native_windows.tasks import require_task_result
from yoke_harness.ssh_mac_baseline_probes import (
    parse_baseline_probes,
    run_baseline_probes,
)
from yoke_harness.standard_baseline_probes import standard_probes

_SECRET = "sk-ant-secret-token-0123456789"
_PYTHON = r"C:\Python312\python.exe"


def _document(*, real_request: bool = False) -> str:
    if real_request:
        probe = next(
            p for p in standard_probes("windows") if p["name"] == "Claude real request"
        )
        probe["argv"][0] = _PYTHON
        return json.dumps({"probes": [probe]})
    return json.dumps(
        {"probes": [{"name": "python", "argv": [_PYTHON, "--version"]}]}
    )


def _typed_bridge_failure() -> HostControlLocalError:
    control = SimpleNamespace(secret_values=(_SECRET,))
    failed = SimpleNamespace(
        returncode=5, stdout=f"token={_SECRET}", stderr=f"Access denied {_SECRET}"
    )
    with pytest.raises(HostControlLocalError) as raised:
        require_task_result(control, failed, phase="terminal_task_start")
    return raised.value


def _control(error: BaseException) -> SimpleNamespace:
    def run_command(argv, *, required_session_context, timeout):
        assert required_session_context == "gui"
        raise error

    return SimpleNamespace(run_command=run_command)


@pytest.mark.parametrize("real_request", [False, True])
def test_typed_windows_bridge_failure_keeps_its_phase_and_recovery(real_request):
    error = _typed_bridge_failure()

    result = prove_document(_control(error), _document(real_request=real_request))

    assert not result.ok
    assert result.error_code == NO_VERDICT_ERROR_CODE
    row = result.evidence["probes"][0]
    assert row["outcome"] == "failed" and row["exit_code"] is None
    assert row["cause"] == "native_windows_task_failed"
    assert row["phase"] == "terminal_task_start"
    assert row["host_exit_code"] == 5
    assert row["recovery"] == error.recovery_hint
    assert "terminal_task_start" in row["reason"]
    assert result.evidence["phase"] == "terminal_task_start"
    assert result.evidence["recovery"] == error.recovery_hint
    assert result.evidence["reason"] == row["reason"]
    receipt = json.dumps(result.evidence)
    assert "SSH" not in receipt
    assert _SECRET not in receipt and "Access denied" not in receipt
    assert "token=" not in receipt


def test_unknown_exception_keeps_the_generic_fallback_without_its_text():
    result = prove_document(
        _control(RuntimeError(f"ssh -i key {_SECRET} failed")), _document()
    )

    assert result.error_code == NO_VERDICT_ERROR_CODE
    row = result.evidence["probes"][0]
    assert row["cause"] == "host_session_command_unavailable"
    assert row["error_type"] == "RuntimeError"
    assert "phase" not in row and "phase" not in result.evidence
    assert result.evidence["recovery"] == (
        "Check SSH reachability and retry the baseline probe."
    )
    assert _SECRET not in json.dumps(result.evidence)


def test_a_typed_failure_with_an_unsafe_code_falls_back_to_generic():
    error = HostControlLocalError(
        code=f"bad code {_SECRET}", phase="terminal_task_start",
        detail="d", recovery_hint="r",
    )

    result = prove_document(_control(error), _document())

    row = result.evidence["probes"][0]
    assert row["cause"] == "host_session_command_unavailable"
    assert row["error_type"] == "HostControlLocalError"
    assert _SECRET not in json.dumps(result.evidence)


def test_staging_refusal_carries_bounded_safe_staging_metadata():
    error = RuntimeError(f"windows_admin_staging_prepare_failed {_SECRET}")
    error.staging_diagnostics = {
        "path": r"C:\Users\private-user\.yoke-stage-abc",
        "sha256": "f" * 64,
        "total_bytes": 9000,
        "last_verified_offset": 0,
        "remote_directory_owned": False,
        "cleanup": "verified_absent",
        "local_cleanup": "verified_absent",
        "steps": [
            {"phase": "prepare", "remaining_seconds": 90.0, "exit_code": 1,
             "outcome": "RuntimeError", "duration_seconds": 1.25},
            {"phase": f"leak {_SECRET}!", "exit_code": 2},
        ],
    }

    result = prove_document(_control(error), _document())

    assert result.error_code == NO_VERDICT_ERROR_CODE
    row = result.evidence["probes"][0]
    assert row["cause"] == "host_session_command_unavailable"
    assert row["staging"] == {
        "total_bytes": 9000,
        "last_verified_offset": 0,
        "remote_directory_owned": False,
        "cleanup": "verified_absent",
        "local_cleanup": "verified_absent",
        "steps": [
            {"phase": "prepare", "exit_code": 1, "outcome": "RuntimeError",
             "duration_seconds": 1.25},
            {"exit_code": 2},
        ],
    }
    receipt = json.dumps(result.evidence)
    for private in (_SECRET, "private-user", "f" * 64, "prepare_failed"):
        assert private not in receipt


def test_macos_raise_keeps_the_terminal_bridge_recovery():
    result = run_baseline_probes(
        parse_baseline_probes(
            json.dumps({"probes": [{"name": "p", "argv": ["/bin/true"]}]})
        ),
        run_gui_command=lambda argv, timeout: (_ for _ in ()).throw(
            RuntimeError(_SECRET)
        ),
    )

    row = result.evidence["probes"][0]
    assert result.error_code == NO_VERDICT_ERROR_CODE
    assert row["cause"] == "bridge_call_raised"
    assert "Terminal.app" in row["recovery"]
    assert _SECRET not in json.dumps(result.evidence)
