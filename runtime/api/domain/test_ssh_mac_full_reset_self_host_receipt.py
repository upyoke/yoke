"""Receipt coverage for the Test Machine reset's self-host stack phases.

Companion to `test_ssh_mac_full_reset_self_host.py`, which drives the shell
functions directly. These tests exercise the Python parser against the fake
transport: what the reset reports about the container runtime it could reach.
"""

from __future__ import annotations

import pytest

from runtime.api.domain.ssh_mac_full_reset_test_support import (
    FakeResetTransport,
    closed_reset_stdout,
)
from runtime.api.domain.ssh_mac_full_reset_shared_test_support import _run
from yoke_contracts.ssh_mac_full_reset_contract import (
    RESET_FAILURE_PREFIX,
    RESET_PHASES,
)
from yoke_contracts.ssh_mac_full_reset_self_host_contract import (
    CONTAINER_RUNTIME_PATHS,
    CONTAINER_RUNTIME_STARTER_PATHS,
    DOCKER_DESKTOP_CLI,
    RESET_SELF_HOST_KIND_DOCKER_UNREACHABLE,
    RESET_SELF_HOST_KIND_RUNTIME_STOP_FAILED,
    RESET_SELF_HOST_RECOVERY,
    RESET_SELF_HOST_STATE_PREFIX,
)


def _unreachable_stdout(phase: str, runtime: str) -> str:
    return "\n".join(
        (
            RESET_FAILURE_PREFIX + RESET_PHASES[phase],
            f"{RESET_SELF_HOST_STATE_PREFIX}"
            f"{RESET_SELF_HOST_KIND_DOCKER_UNREACHABLE} {runtime}",
        )
    )


@pytest.mark.parametrize("runtime", [CONTAINER_RUNTIME_PATHS[1], DOCKER_DESKTOP_CLI])
@pytest.mark.parametrize("phase", ["stop_self_host_stack", "verify_restored_home"])
def test_reset_refuses_naming_the_runtime_whose_daemon_could_not_list(
    phase: str, runtime: str,
) -> None:
    transport = FakeResetTransport(
        _unreachable_stdout(phase, runtime), reset_returncode=1
    )

    result = _run(transport)

    assert not result.ok
    assert result.error_code == f"test_mac_reset_{phase}_failed"
    assert result.evidence["reset_phase"] == phase
    start = f"{runtime} desktop start" if runtime == DOCKER_DESKTOP_CLI else "colima start"
    recovery = RESET_SELF_HOST_RECOVERY[RESET_SELF_HOST_KIND_DOCKER_UNREACHABLE]
    assert result.evidence["self_host_state"] == {
        "runtime": runtime,
        "reason": RESET_SELF_HOST_KIND_DOCKER_UNREACHABLE,
        "recovery": recovery.format(runtime=runtime, start=start),
    }
    assert start in str(result.evidence["self_host_state"]["recovery"])


def test_reset_rejects_an_unreachable_detail_naming_a_foreign_client() -> None:
    transport = FakeResetTransport(
        _unreachable_stdout("stop_self_host_stack", "/tmp/docker"),
        reset_returncode=1,
    )

    result = _run(transport)

    # The program resolves its client from the contract's fixed locations, so
    # any other path means the receipt did not come from that program.
    assert not result.ok
    assert result.error_code == "test_mac_reset_failed"
    assert "self_host_state" not in result.evidence


def test_a_reachable_empty_daemon_reports_reachable_with_zero_counts() -> None:
    result = _run(FakeResetTransport(closed_reset_stdout(self_host_stack_reachable=1)))

    assert result.ok
    state = result.evidence["self_host_state"]
    assert state["stack_reachable"] is True
    assert (state["containers_removed"], state["volumes_removed"]) == (0, 0)
    assert state["images_removed"] == 0


def test_a_host_without_a_runtime_client_passes_unreachable() -> None:
    result = _run(FakeResetTransport(closed_reset_stdout(self_host_stack_reachable=0)))

    assert result.ok
    assert result.evidence["self_host_state"]["stack_reachable"] is False


@pytest.mark.parametrize(
    "stdout",
    [
        closed_reset_stdout(self_host_stack_reachable=2),
        # Removals only come from a daemon that listed the stack.
        closed_reset_stdout(self_host_stack_reachable=0, self_host_containers=1),
    ],
)
def test_reset_rejects_an_inconsistent_reachability_line(stdout: str) -> None:
    result = _run(FakeResetTransport(stdout))

    assert not result.ok
    assert result.error_code == "test_mac_reset_output_invalid"


@pytest.mark.parametrize("starter", [CONTAINER_RUNTIME_STARTER_PATHS[1], DOCKER_DESKTOP_CLI])
def test_reset_refuses_naming_the_runtime_it_started_and_could_not_stop(starter: str) -> None:
    transport = FakeResetTransport(
        "\n".join(
            (
                RESET_FAILURE_PREFIX + RESET_PHASES["verify_restored_home"],
                f"{RESET_SELF_HOST_STATE_PREFIX}"
                f"{RESET_SELF_HOST_KIND_RUNTIME_STOP_FAILED} {starter}",
            )
        ),
        reset_returncode=1,
    )

    result = _run(transport)

    assert not result.ok
    assert result.error_code == "test_mac_reset_verify_restored_home_failed"
    stop = f"{starter} desktop stop" if starter == DOCKER_DESKTOP_CLI else "colima stop"
    recovery = RESET_SELF_HOST_RECOVERY[RESET_SELF_HOST_KIND_RUNTIME_STOP_FAILED]
    assert result.evidence["self_host_state"] == {
        "runtime": starter,
        "reason": RESET_SELF_HOST_KIND_RUNTIME_STOP_FAILED,
        "recovery": recovery.format(runtime=starter, stop=stop),
    }
