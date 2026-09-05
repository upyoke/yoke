"""Driver coverage for the dedicated Test Mac golden-baseline restore."""

from __future__ import annotations

import pytest
import shlex

from runtime.api.domain.ssh_mac_full_reset_test_support import (
    FakeResetTransport,
    GOLDEN_BASELINE_PATH,
    closed_reset_stdout,
)
from yoke_cli.config import path_doctor
from yoke_core.domain.ssh_mac_full_reset import execute_full_test_mac_reset
from yoke_core.domain.ssh_mac_full_reset_contract import (
    FULL_DISK_ACCESS_PROBE_PATH,
    FULL_RESET_REMOTE_PATH,
    RESET_FAILURE_PREFIX,
    RESET_PHASES,
)
from yoke_core.domain.ssh_mac_full_reset_script import FULL_RESET_SCRIPT
from yoke_harness.ssh_mac_full_reset import is_safe_test_mac_home
from yoke_harness.ssh_mac_full_reset_contract import (
    INSTALLER_TEMP_PATH,
    RESET_ABSENT_KIND_LEFTOVER,
    RESET_ABSENT_PATH_PREFIX,
    RESET_ABSENT_RECOVERY,
    RESET_RESTORE_UNRESTORED_PREFIX,
    SELF_HOST_COMPOSE_PROJECT,
)


HOME = "/Users/tester"


def _run(transport: FakeResetTransport, **overrides):
    arguments = {
        "run_remote": transport.run,
        "upload_text": transport.upload,
        "home": HOME,
        "golden_baseline_path": GOLDEN_BASELINE_PATH,
    }
    arguments.update(overrides)
    return execute_full_test_mac_reset(**arguments)


@pytest.mark.parametrize(
    "home",
    ["", "/", "~", "$HOME", "/Users", "/Users/", "/Users/shared", "/Users/a/b"],
)
def test_reset_rejects_any_non_explicit_dedicated_mac_home(home: str) -> None:
    transport = FakeResetTransport(closed_reset_stdout())

    result = _run(transport, home=home)

    assert not is_safe_test_mac_home(home)
    assert not result.ok
    assert result.error_code == "unsafe_test_mac_home"
    assert transport.uploads == {}
    assert transport.commands == []


def test_reset_refuses_a_host_that_declares_no_captured_baseline() -> None:
    transport = FakeResetTransport(closed_reset_stdout())

    result = _run(transport, golden_baseline_path=None)

    # Enumerating residue is not a fallback. A machine with no captured
    # baseline cannot reach this baseline at all.
    assert not result.ok
    assert result.error_code == "test_mac_golden_baseline_not_declared"
    assert transport.uploads == {}


@pytest.mark.parametrize(
    "golden",
    [f"{HOME}/golden", f"{HOME}", "relative/golden", "/Users/Shared/../tester/g"],
)
def test_reset_refuses_a_baseline_the_clear_would_destroy(golden: str) -> None:
    transport = FakeResetTransport(closed_reset_stdout())

    result = _run(transport, golden_baseline_path=golden)

    assert not result.ok
    assert result.error_code == "test_mac_golden_baseline_unsafe"
    assert transport.commands == []


def test_reset_uploads_mode_0700_and_accepts_only_closed_outcomes() -> None:
    transport = FakeResetTransport(closed_reset_stdout(restored_entries=22))

    result = _run(transport)

    assert result.ok
    assert transport.uploads == {FULL_RESET_REMOTE_PATH: FULL_RESET_SCRIPT}
    assert [shlex.split(command) for command, _timeout in transport.commands] == [
        ["/bin/rm", "-f", "--", FULL_RESET_REMOTE_PATH],
        ["/bin/chmod", "0700", FULL_RESET_REMOTE_PATH],
        [FULL_RESET_REMOTE_PATH, HOME, GOLDEN_BASELINE_PATH],
        ["/bin/rm", "-f", "--", FULL_RESET_REMOTE_PATH],
    ]
    assert set(result.evidence) == {
        "paths",
        "baseline_state",
        "path_state",
        "process_state",
        "relay_service_state",
        "self_host_state",
    }
    assert result.evidence["baseline_state"] == {
        "golden_baseline_path": GOLDEN_BASELINE_PATH,
        "restored_entries": 22,
        "preserved_entries": [".ssh", "Library/Application Support/com.apple.TCC"],
    }
    rows = {row["path"]: row["outcome"] for row in result.evidence["paths"]}
    assert rows[GOLDEN_BASELINE_PATH] == "restored"
    assert rows[FULL_DISK_ACCESS_PROBE_PATH] == "readable"
    assert rows[f"{HOME}/.ssh"] == "preserved"
    assert rows[f"{HOME}/Library/Application Support/com.apple.TCC"] == "preserved"
    assert rows[f"{HOME}/.yoke"] == "absent"
    assert rows[f"{HOME}/.local/bin/yoke"] == "absent"
    # The shared tool directory is reported for what it is, not claimed gone:
    # the user's own command-line tools live there.
    assert rows[str(path_doctor.tool_bin_dir({"HOME": HOME}))] == (
        "carries-no-yoke-tool"
    )
    assert result.evidence["path_state"] == {
        "launcher": f"{HOME}/.local/bin/yoke",
        "launcher_present": False,
        "tool_bin_dir": f"{HOME}/.local/bin",
        "yoke_tools_resolve": False,
    }


def test_reset_passes_a_restore_sized_timeout_to_the_remote_program() -> None:
    transport = FakeResetTransport(closed_reset_stdout())

    _run(transport)

    assert transport.commands[2][1] == 900


def test_reset_fails_closed_on_extra_output_and_always_cleans_script() -> None:
    transport = FakeResetTransport(closed_reset_stdout() + "\nYOKE_EXTRA")

    result = _run(transport)

    assert not result.ok
    assert result.error_code == "test_mac_reset_output_invalid"
    assert shlex.split(transport.commands[-1][0]) == [
        "/bin/rm",
        "-f",
        "--",
        FULL_RESET_REMOTE_PATH,
    ]


def test_reset_refuses_a_receipt_claiming_an_empty_restored_home() -> None:
    transport = FakeResetTransport(closed_reset_stdout(restored_entries=0))

    result = _run(transport)

    assert not result.ok
    assert result.error_code == "test_mac_reset_output_invalid"


def test_reset_names_the_full_disk_access_phase_when_the_grant_is_missing() -> None:
    transport = FakeResetTransport(
        RESET_FAILURE_PREFIX + RESET_PHASES["assert_full_disk_access"],
        reset_returncode=1,
    )

    result = _run(transport)

    assert not result.ok
    assert result.error_code == "test_mac_reset_assert_full_disk_access_failed"
    assert result.evidence["reset_phase"] == "assert_full_disk_access"
    rows = {row["path"]: row["outcome"] for row in result.evidence["paths"]}
    assert rows[GOLDEN_BASELINE_PATH] == "not-restored"


@pytest.mark.parametrize(
    "phase",
    ["validate_golden", "clear_home", "restore_golden", "verify_restored_home"],
)
def test_reset_reports_every_registered_restore_phase_failure(phase: str) -> None:
    transport = FakeResetTransport(
        RESET_FAILURE_PREFIX + RESET_PHASES[phase],
        reset_returncode=1,
    )

    result = _run(transport)

    assert not result.ok
    assert result.error_code == f"test_mac_reset_{phase}_failed"


def test_reset_fails_closed_when_matching_processes_survive_the_reap() -> None:
    transport = FakeResetTransport(
        "\n".join(
            (
                RESET_FAILURE_PREFIX + RESET_PHASES["reap_processes"],
                "1 2 3.50",
            )
        ),
        reset_returncode=1,
    )

    result = _run(transport)

    assert not result.ok
    assert result.error_code == "test_mac_reset_reap_processes_failed"
    assert result.evidence["process_state"] == {
        "surviving_reap_failures": 1,
        "surviving_matches": 2,
        "load_average": 3.5,
    }


def test_reset_names_the_unmet_absent_temp_path_and_its_recovery() -> None:
    transport = FakeResetTransport(
        "\n".join(
            (
                RESET_FAILURE_PREFIX + RESET_PHASES["verify_restored_home"],
                RESET_ABSENT_PATH_PREFIX
                + RESET_ABSENT_KIND_LEFTOVER
                + " "
                + INSTALLER_TEMP_PATH,
            )
        ),
        reset_returncode=1,
    )

    result = _run(transport)

    assert not result.ok
    assert result.error_code == "test_mac_reset_verify_restored_home_failed"
    assert result.evidence["absent_state"] == {
        "path": INSTALLER_TEMP_PATH,
        "reason": RESET_ABSENT_KIND_LEFTOVER,
        "recovery": RESET_ABSENT_RECOVERY[RESET_ABSENT_KIND_LEFTOVER].format(
            path=INSTALLER_TEMP_PATH
        ),
    }


def test_reset_names_the_entries_a_stopped_restore_could_not_return() -> None:
    transport = FakeResetTransport(
        "\n".join(
            (
                RESET_FAILURE_PREFIX + RESET_PHASES["restore_golden"],
                RESET_RESTORE_UNRESTORED_PREFIX + "2 Library Documents",
            )
        ),
        reset_returncode=1,
    )

    result = _run(transport)

    assert not result.ok
    assert result.error_code == "test_mac_reset_restore_golden_failed"
    # A phase name on its own is a receipt that cannot be acted on: diagnosis
    # then means repeating the whole restore on the host to watch where it
    # stopped, which is exactly what this evidence removes.
    assert result.evidence["restore_state"] == {
        "unrestored_entry_count": 2,
        "unrestored_entries": ["Library", "Documents"],
    }


def test_reset_reports_what_the_self_host_teardown_freed() -> None:
    transport = FakeResetTransport(
        closed_reset_stdout(
            self_host_containers=2,
            self_host_volumes=1,
            self_host_images=2,
        )
    )

    result = _run(transport)

    assert result.ok
    assert result.evidence["self_host_state"] == {
        "compose_project": SELF_HOST_COMPOSE_PROJECT,
        "containers_removed": 2,
        "volumes_removed": 1,
        "images_removed": 2,
        "stack_reachable": False,
    }


def test_reset_rejects_unregistered_failure_output() -> None:
    transport = FakeResetTransport("YOKE_RESET_FAILED_SOMETHING", reset_returncode=1)

    result = _run(transport)

    assert not result.ok
    assert result.error_code == "test_mac_reset_failed"


def test_reset_reports_cleanup_failure_even_after_a_clean_restore() -> None:
    transport = FakeResetTransport(closed_reset_stdout())
    transport.cleanup_returncode = 1

    result = _run(transport)

    assert not result.ok
    assert result.error_code == "test_mac_reset_script_cleanup_failed"
