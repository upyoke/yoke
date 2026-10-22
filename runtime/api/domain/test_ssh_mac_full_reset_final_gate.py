"""Final validation must finish before the reset emits success counters."""

from pathlib import Path
import subprocess

import pytest

from runtime.api.domain.ssh_mac_full_reset_test_support import (
    FakeResetTransport,
    GOLDEN_BASELINE_PATH,
    assignment,
    isolated_shell_env,
    require_zsh,
)
from yoke_harness.ssh_mac_full_reset import execute_full_test_machine_reset
from yoke_harness.ssh_mac_full_reset_contract import (
    FULL_RESET_MARKER,
    RESET_FAILURE_PREFIX,
    RESET_PHASES,
)
from yoke_harness.ssh_mac_full_reset_receipt import closed_outcomes, failure_outcome
from yoke_harness.ssh_mac_full_reset_script import FULL_RESET_SCRIPT


def _run_final_validation(
    tmp_path: Path, *, failed: int, matches: int, load: str
) -> subprocess.CompletedProcess:
    binary = require_zsh()
    marker = '\nreset_step="$reset_phase_validate_home"\n'
    functions, separator, driver = FULL_RESET_SCRIPT.partition(marker)
    assert separator
    # Run the generated driver and EXIT trap. Replace host operations so this
    # regression never reads, clears, restores or reaps anything on the host.
    stubs = "\n".join(
        f"{name}() {{ return 0; }}"
        for name in (
            "validate_home",
            "assert_full_disk_access",
            "validate_golden",
            "unload_relay_service",
            "reap_processes",
            "stop_self_host_stack",
            "clear_home",
            "verify_restored_home",
            "cleanup_scratch",
        )
    )
    stubs += "\nrestore_golden() { restored_entry_count=22; }\n"
    stubs += (
        f"count_reap_matches() {{ reap_failed_count={failed}; "
        f"reap_match_count={matches}; }}\n"
    )
    stubs += (
        "record_load_average() { "
        + assignment("load_average_1min", load)
        + "; cpu_count=4; }\n"
    )
    return subprocess.run(
        [
            binary,
            "-f",
            "-c",
            functions + stubs + separator + driver,
            "yoke-reset",
            "/Users/tester",
            GOLDEN_BASELINE_PATH,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
        env=isolated_shell_env(tmp_path / "shell-home"),
    )


def _adapt(result: subprocess.CompletedProcess):
    transport = FakeResetTransport(result.stdout, reset_returncode=result.returncode)
    return execute_full_test_machine_reset(
        run_remote=transport.run,
        upload_text=transport.upload,
        home="/Users/tester",
        golden_baseline_path=GOLDEN_BASELINE_PATH,
    )


@pytest.mark.parametrize(
    ("failed", "matches", "load"),
    [(1, 0, "1.25"), (0, 2, "1.25"), (0, 0, "4.25"), (0, 0, "")],
)
def test_final_gate_failure_retains_phase_and_process_detail(
    tmp_path, failed, matches, load
):
    result = _run_final_validation(tmp_path, failed=failed, matches=matches, load=load)
    assert result.returncode == 1
    assert result.stderr == ""
    detail = f"{failed} {matches} {load or '0'}"
    assert result.stdout.splitlines() == [
        RESET_FAILURE_PREFIX + RESET_PHASES["reap_processes"],
        detail,
    ]
    assert failure_outcome(result.stdout) == ("reap_processes", False, detail)
    assert closed_outcomes(result.stdout) is None
    adapted = _adapt(result)
    assert not adapted.ok
    assert adapted.error_code == "test_mac_reset_reap_processes_failed"
    assert adapted.evidence["reset_phase"] == "reap_processes"
    assert adapted.evidence["process_state"] == {
        "surviving_reap_failures": failed,
        "surviving_matches": matches,
        "load_average": float(load or "0"),
    }
    assert adapted.evidence["paths"][2]["outcome"] == "removed"


def test_success_counters_follow_final_validation(tmp_path):
    result = _run_final_validation(tmp_path, failed=0, matches=0, load="4.00")
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.splitlines()[-1] == FULL_RESET_MARKER
    assert failure_outcome(result.stdout) is None
    assert closed_outcomes(result.stdout) == {
        "restored_entries": 22,
        "relay_services_unloaded": 0,
        "self_host_containers_removed": 0,
        "self_host_volumes_removed": 0,
        "self_host_images_removed": 0,
        "reaped_processes": 0,
        "load_average": 4.0,
    }
    adapted = _adapt(result)
    assert adapted.ok
    assert adapted.evidence["baseline_state"]["restored_entries"] == 22
    assert adapted.evidence["process_state"] == {
        "reaped_processes": 0,
        "surviving_matches": 0,
        "load_average": 4.0,
    }
