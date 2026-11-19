"""Fake container runtime and Colima for the reset's self-host shell tests."""

from __future__ import annotations

from pathlib import Path
import shlex
import subprocess

from runtime.api.domain.ssh_mac_full_reset_test_support import (
    function_program,
    require_zsh,
)
from yoke_contracts.ssh_mac_full_reset_self_host_contract import (
    COMPOSE_PROJECT_LABEL,
    RESET_SELF_HOST_KIND_DOCKER_UNREACHABLE,
    RESET_SELF_HOST_KIND_RUNTIME_STOP_FAILED,
    RESET_SELF_HOST_STATE_PREFIX,
    SELF_HOST_COMPOSE_PROJECT,
)


#: A container client that answers from files, so the teardown's own selection
#: and removal argv are the subject rather than a live daemon's behavior.
FAKE_RUNTIME = """#!/bin/zsh
state="$FAKE_RUNTIME_STATE"
print -r -- "$@" >> "$state/argv.log"
subject="${@[-1]}"
if [[ -e "$state/down" ]]; then
  print -u2 -r -- "Cannot connect to the Docker daemon. Is the docker daemon running?"
  exit 1
fi
case "$1 $2" in
  "ps -aq") /bin/cat "$state/containers" 2>/dev/null || true ;;
  "volume ls") /bin/cat "$state/volumes" 2>/dev/null || true ;;
  "inspect --format") print -r -- "image-for-$subject" ;;
  "rm --force")
    print -r -- "$subject" >> "$state/removed-containers"
    FORGET_CONTAINER=1
    ;;
  "volume rm")
    print -r -- "$subject" >> "$state/removed-volumes"
    /usr/bin/sed -i '' "/^$subject$/d" "$state/volumes"
    ;;
  "image rm") print -r -- "$subject" >> "$state/removed-images" ;;
  *) exit 1 ;;
esac
if [[ -n "${FORGET_CONTAINER:-}" && -z "${FAKE_RUNTIME_KEEPS_CONTAINERS:-}" ]]; then
  /usr/bin/sed -i '' "/^$subject$/d" "$state/containers"
fi
"""


#: A Colima stand-in that brings the fake daemon up or down through the same
#: state directory, failing on demand so the refusals are reachable.
FAKE_STARTER = """#!/bin/zsh
state="$FAKE_RUNTIME_STATE"
print -r -- "$1" >> "$state/starter.log"
[[ ! -e "$state/$1-fails" ]] || exit 1
case "$1" in
  start) /bin/rm -f -- "$state/down" ;;
  stop) : > "$state/down" ;;
  *) exit 1 ;;
esac
"""

#: Where no starter is installed, as on a Docker Desktop or runtime-free host.
NO_STARTER = Path("/nonexistent/yoke-test/colima")


def fake_starter(tmp_path: Path) -> Path:
    """Install the Colima stand-in beside the fake client."""
    starter = tmp_path / "fake-colima"
    starter.write_text(FAKE_STARTER)
    starter.chmod(0o755)
    return starter


def fake_runtime(tmp_path: Path, *, containers: tuple[str, ...]) -> tuple[Path, Path]:
    """Install the answering client and its state directory."""
    state = tmp_path / "runtime-state"
    state.mkdir()
    (state / "containers").write_text("".join(f"{name}\n" for name in containers))
    (state / "volumes").write_text("".join(f"{name}-data\n" for name in containers))
    client = tmp_path / "fake-docker"
    client.write_text(FAKE_RUNTIME)
    client.chmod(0o755)
    return client, state


def run(
    lines: tuple[str, ...],
    *,
    state: Path | None = None,
    keeps_containers: bool = False,
    daemon_down: bool = False,
) -> subprocess.CompletedProcess:
    binary = require_zsh()
    env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(state or Path("/tmp"))}
    if state is not None:
        env["FAKE_RUNTIME_STATE"] = str(state)
    if keeps_containers:
        env["FAKE_RUNTIME_KEEPS_CONTAINERS"] = "1"
    if daemon_down:
        assert state is not None
        (state / "down").touch()
    return subprocess.run(
        [binary, "-f"],
        input="\n".join(lines),
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def self_host_lines(
    client: Path, *, anchor: str, starter: Path = NO_STARTER
) -> tuple[str, ...]:
    return (
        function_program(),
        f"self_host_state_prefix={shlex.quote(RESET_SELF_HOST_STATE_PREFIX)}",
        "self_host_kind_docker_unreachable="
        + shlex.quote(RESET_SELF_HOST_KIND_DOCKER_UNREACHABLE),
        "self_host_kind_runtime_stop_failed="
        + shlex.quote(RESET_SELF_HOST_KIND_RUNTIME_STOP_FAILED),
        f"container_runtime_starter_paths=({shlex.quote(str(starter))})",
        "container_runtime_start_timeout=5",
        f"container_runtime_paths=({shlex.quote(str(client))})",
        f"compose_project_label={shlex.quote(COMPOSE_PROJECT_LABEL)}",
        f"self_host_compose_project={shlex.quote(SELF_HOST_COMPOSE_PROJECT)}",
        f"container_runtime_anchor={shlex.quote(anchor)}",
        "container_runtime_stop_timeout=1",
        'failure_detail=""',
    )


def teardown_lines(
    client: Path,
    *,
    anchor: str = "no-such-application",
    starter: Path = NO_STARTER,
) -> tuple[str, ...]:
    return (
        *self_host_lines(client, anchor=anchor, starter=starter),
        "stop_self_host_stack || print -r -- TEARDOWN_FAILED",
        'print -r -- "REMOVED $self_host_containers_removed '
        '$self_host_volumes_removed $self_host_images_removed"',
        'print -r -- "REACHABLE $self_host_stack_reachable"',
        'print -r -- "DETAIL $failure_detail"',
    )
