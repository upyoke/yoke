"""The reset starts a stopped Colima to list the stack, then stops it again.

A stopped Colima is the normal state when a test Mac resets, and its VM disk
outside the restored home keeps whatever the last walk left. These tests drive
the shell functions against a fake client and a fake Colima sharing one state
directory, so starting the runtime is what makes the fake daemon answer.
"""

from __future__ import annotations

import pytest

from pathlib import Path

from runtime.api.domain.ssh_mac_full_reset_self_host_test_support import (
    fake_runtime,
    fake_starter,
    run,
    self_host_lines,
    teardown_lines,
)
from yoke_contracts.ssh_mac_full_reset_self_host_contract import (
    RESET_SELF_HOST_KIND_DOCKER_UNREACHABLE,
    RESET_SELF_HOST_KIND_RUNTIME_STOP_FAILED,
    RESET_SELF_HOST_STATE_PREFIX,
)



def _starter_calls(state: Path) -> list[str]:
    log = state / "starter.log"
    return log.read_text().split() if log.exists() else []


def _reset_lines(client: Path, starter: Path) -> tuple[str, ...]:
    # Teardown, then the restore step verify runs once it has seen the stack.
    return (
        *teardown_lines(client, starter=starter),
        "restore_container_runtime_state || print -r -- RESTORE_FAILED",
        'print -r -- "RESTORED_DETAIL $failure_detail"',
    )


@pytest.mark.macos_only(reason="executes a macOS reset or capture program in /bin/zsh")
def test_a_stopped_runtime_is_started_listed_cleaned_and_stopped_again(
    tmp_path: Path,
) -> None:
    client, state = fake_runtime(tmp_path, containers=("core",))
    starter = fake_starter(tmp_path)

    result = run(_reset_lines(client, starter), state=state, daemon_down=True)

    assert "TEARDOWN_FAILED" not in result.stdout, result.stdout + result.stderr
    assert "RESTORE_FAILED" not in result.stdout, result.stdout + result.stderr
    # The leftovers lived in the stopped VM; only starting it could see them.
    assert "REMOVED 1 1 1" in result.stdout
    assert "REACHABLE 1" in result.stdout
    assert _starter_calls(state) == ["status", "start", "status", "stop"]
    assert (state / "down").exists()


@pytest.mark.macos_only(reason="executes a macOS reset or capture program in /bin/zsh")
def test_a_running_colima_the_client_cannot_find_is_reached_by_its_socket(
    tmp_path: Path,
) -> None:
    client, state = fake_runtime(tmp_path, containers=("core",))
    starter = fake_starter(tmp_path)
    # Colima is up, but the client targets /var/run/docker.sock because the
    # restored home carries no Colima docker context: test-mac-studio's case.
    (state / "needs-socket").touch()

    result = run(_reset_lines(client, starter), state=state)

    assert "TEARDOWN_FAILED" not in result.stdout, result.stdout + result.stderr
    assert "RESTORE_FAILED" not in result.stdout, result.stdout + result.stderr
    assert "REMOVED 1 1 1" in result.stdout
    assert "REACHABLE 1" in result.stdout
    # Already running, so the reset neither starts nor stops it.
    assert _starter_calls(state) == ["status", "status"]
    assert not (state / "down").exists()


@pytest.mark.macos_only(reason="executes a macOS reset or capture program in /bin/zsh")
def test_a_running_runtime_is_left_running(tmp_path: Path) -> None:
    client, state = fake_runtime(tmp_path, containers=())
    starter = fake_starter(tmp_path)

    result = run(_reset_lines(client, starter), state=state)

    assert "REACHABLE 1" in result.stdout, result.stdout + result.stderr
    assert "RESTORE_FAILED" not in result.stdout
    assert _starter_calls(state) == []
    assert not (state / "down").exists()


@pytest.mark.macos_only(reason="executes a macOS reset or capture program in /bin/zsh")
def test_a_runtime_that_will_not_start_refuses_naming_the_client(
    tmp_path: Path,
) -> None:
    client, state = fake_runtime(tmp_path, containers=("core",))
    starter = fake_starter(tmp_path)
    (state / "start-fails").touch()

    result = run(teardown_lines(client, starter=starter), state=state, daemon_down=True)

    assert "TEARDOWN_FAILED" in result.stdout, result.stdout + result.stderr
    assert "REACHABLE 0" in result.stdout
    assert (
        f"DETAIL {RESET_SELF_HOST_STATE_PREFIX}"
        f"{RESET_SELF_HOST_KIND_DOCKER_UNREACHABLE} {client}"
    ) in result.stdout
    assert not (state / "removed-containers").exists()


@pytest.mark.macos_only(reason="executes a macOS reset or capture program in /bin/zsh")
def test_a_runtime_the_reset_cannot_stop_again_refuses_naming_the_starter(
    tmp_path: Path,
) -> None:
    client, state = fake_runtime(tmp_path, containers=())
    starter = fake_starter(tmp_path)
    (state / "stop-fails").touch()

    result = run(_reset_lines(client, starter), state=state, daemon_down=True)

    assert "TEARDOWN_FAILED" not in result.stdout, result.stdout + result.stderr
    assert "RESTORE_FAILED" in result.stdout
    assert (
        f"RESTORED_DETAIL {RESET_SELF_HOST_STATE_PREFIX}"
        f"{RESET_SELF_HOST_KIND_RUNTIME_STOP_FAILED} {starter}"
    ) in result.stdout


@pytest.mark.macos_only(reason="executes a macOS reset or capture program in /bin/zsh")
def test_verify_lists_a_runtime_this_reset_started(tmp_path: Path) -> None:
    client, state = fake_runtime(tmp_path, containers=())
    starter = fake_starter(tmp_path)
    lines = (
        *self_host_lines(client, anchor="no-such-application", starter=starter),
        "stop_self_host_stack || print -r -- TEARDOWN_FAILED",
        # A container appearing after the teardown must fail verify, which
        # only a daemon still up at verify can show.
        f"print -r -- late > {state}/containers",
        "self_host_stack_is_absent || print -r -- VERIFY_FAILED",
    )

    result = run(lines, state=state, daemon_down=True)

    assert "TEARDOWN_FAILED" not in result.stdout, result.stdout + result.stderr
    assert "VERIFY_FAILED" in result.stdout


@pytest.mark.macos_only(reason="executes a macOS reset or capture program in /bin/zsh")
def test_verify_reaches_colima_after_the_restore_drops_its_docker_context(
    tmp_path: Path,
) -> None:
    client, state = fake_runtime(tmp_path, containers=())
    starter = fake_starter(tmp_path)
    (state / "needs-socket").touch()
    (state / "context").touch()
    lines = (
        *self_host_lines(client, anchor="no-such-application", starter=starter),
        "stop_self_host_stack || print -r -- TEARDOWN_FAILED",
        # The clear and restore replace the home holding Colima's context.
        f"/bin/rm -f -- {state}/context",
        "self_host_stack_is_absent || print -r -- VERIFY_FAILED",
        'print -r -- "DETAIL $failure_detail"',
    )

    result = run(lines, state=state)

    # test-mac-studio: the stop phase listed through the context, then verify
    # fell back to /var/run/docker.sock and refused a healthy Colima.
    assert "TEARDOWN_FAILED" not in result.stdout, result.stdout + result.stderr
    assert "VERIFY_FAILED" not in result.stdout, result.stdout + result.stderr
    assert _starter_calls(state) == ["status", "status"]


@pytest.mark.macos_only(reason="executes a macOS reset program in /bin/zsh")
@pytest.mark.parametrize("daemon_down", [True, False])
def test_docker_desktop_uses_its_own_socket_and_keeps_its_prior_state(
    tmp_path: Path, daemon_down: bool
) -> None:
    fake_client, state = fake_runtime(tmp_path, containers=("core",))
    client = state / ".docker/bin/docker"
    client.parent.mkdir(parents=True)
    (state / "needs-socket").touch()
    body = fake_client.read_text().replace(
        'unix://$state/docker.sock', 'unix://$state/.docker/run/docker.sock'
    )
    body = body.replace('subject=', r"""
case "$1 ${2:-}" in
  'desktop start') print start >> "$state/desktop.log"; /bin/rm "$state/down"; exit ;;
  'desktop stop') print stop >> "$state/desktop.log"; touch "$state/down"; exit ;;
esac
subject=""")
    client.write_text(body)
    client.chmod(0o755)

    lines = (
        *self_host_lines(client, anchor="no-such-application"),
        'container_runtime_paths=("$docker_desktop_cli")',
        'docker_desktop_is_running() { [[ ! -e "$home/down" ]]; }',
        'export DOCKER_CONTEXT=wrong-context',
        'stop_self_host_stack || print -r -- TEARDOWN_FAILED',
        'self_host_stack_is_absent || print -r -- VERIFY_FAILED',
        'restore_container_runtime_state || print -r -- RESTORE_FAILED',
        'print -r -- "REACHABLE $self_host_stack_reachable"',
    )
    result = run(lines, state=state, daemon_down=daemon_down)

    assert "FAILED" not in result.stdout, result.stdout + result.stderr
    assert "REACHABLE 1" in result.stdout
    assert (state / "removed-containers").read_text().strip() == "core"
    assert (state / "down").exists() == daemon_down
    log = state / "desktop.log"
    assert (log.read_text().splitlines() if log.exists() else []) == (
        ["start", "stop"] if daemon_down else []
    )
