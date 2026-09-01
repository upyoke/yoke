"""Self-host teardown coverage for the dedicated Test Mac reset."""

from __future__ import annotations

from pathlib import Path
import shlex
import subprocess

from runtime.api.domain.ssh_mac_full_reset_test_support import (
    function_program as _function_program,
    require_zsh as _require_zsh,
)
from yoke_harness.ssh_mac_full_reset_contract import (
    COMPOSE_PROJECT_LABEL,
    RESET_PHASES,
    SELF_HOST_COMPOSE_PROJECT,
    YOKE_ABSENT_RELATIVE_DIRECTORIES,
)
from yoke_harness.ssh_mac_full_reset_receipt import unrestored_detail
from yoke_harness.ssh_mac_full_reset_script import FULL_RESET_SCRIPT


#: A container client that answers from files, so the teardown's own selection
#: and removal argv are the subject rather than a live daemon's behavior.
FAKE_RUNTIME = """#!/bin/zsh
state="$FAKE_RUNTIME_STATE"
print -r -- "$@" >> "$state/argv.log"
subject="${@[-1]}"
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


def _fake_runtime(tmp_path: Path, *, containers: tuple[str, ...]) -> tuple[Path, Path]:
    """Install the answering client and its state directory."""
    state = tmp_path / "runtime-state"
    state.mkdir()
    (state / "containers").write_text("".join(f"{name}\n" for name in containers))
    (state / "volumes").write_text("".join(f"{name}-data\n" for name in containers))
    client = tmp_path / "fake-docker"
    client.write_text(FAKE_RUNTIME)
    client.chmod(0o755)
    return client, state


def _run(
    lines: tuple[str, ...],
    *,
    state: Path | None = None,
    keeps_containers: bool = False,
) -> subprocess.CompletedProcess:
    binary = _require_zsh()
    env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(state or Path("/tmp"))}
    if state is not None:
        env["FAKE_RUNTIME_STATE"] = str(state)
    if keeps_containers:
        env["FAKE_RUNTIME_KEEPS_CONTAINERS"] = "1"
    return subprocess.run(
        [binary, "-f"],
        input="\n".join(lines),
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def _teardown_lines(
    client: Path, *, anchor: str = "no-such-application"
) -> tuple[str, ...]:
    return (
        _function_program(),
        f"container_runtime_paths=({shlex.quote(str(client))})",
        f"compose_project_label={shlex.quote(COMPOSE_PROJECT_LABEL)}",
        f"self_host_compose_project={shlex.quote(SELF_HOST_COMPOSE_PROJECT)}",
        f"container_runtime_anchor={shlex.quote(anchor)}",
        "container_runtime_stop_timeout=1",
        "stop_self_host_stack || print -r -- TEARDOWN_FAILED",
        'print -r -- "REMOVED $self_host_containers_removed '
        '$self_host_volumes_removed $self_host_images_removed"',
    )


def test_teardown_removes_the_bundle_stack_and_reports_what_it_freed(
    tmp_path: Path,
) -> None:
    client, state = _fake_runtime(tmp_path, containers=("core", "db"))

    result = _run(_teardown_lines(client), state=state)

    assert "TEARDOWN_FAILED" not in result.stdout, result.stdout + result.stderr
    assert "REMOVED 2 2 2" in result.stdout, result.stdout + result.stderr
    assert (state / "removed-containers").read_text().split() == ["core", "db"]
    assert (state / "removed-volumes").read_text().split() == [
        "core-data",
        "db-data",
    ]
    # Images are named by the containers that used them, never by image tag: the
    # bundle shares its database image with whatever else the user runs.
    assert sorted((state / "removed-images").read_text().split()) == [
        "image-for-core",
        "image-for-db",
    ]


def test_teardown_selects_only_the_bundle_project(tmp_path: Path) -> None:
    client, state = _fake_runtime(tmp_path, containers=("core",))

    _run(_teardown_lines(client), state=state)

    selectors = [
        line
        for line in (state / "argv.log").read_text().splitlines()
        if "label=" in line
    ]
    assert selectors
    for line in selectors:
        assert f"label={COMPOSE_PROJECT_LABEL}={SELF_HOST_COMPOSE_PROJECT}" in line


def test_teardown_is_a_clean_pass_on_a_host_with_no_container_runtime(
    tmp_path: Path,
) -> None:
    absent = tmp_path / "no-runtime-here"

    result = _run(_teardown_lines(absent), state=tmp_path)

    # A host that never ran a container has nothing to remove, which is a pass
    # rather than a skip: the end state the phase exists to reach is already met.
    assert "TEARDOWN_FAILED" not in result.stdout, result.stdout + result.stderr
    assert "REMOVED 0 0 0" in result.stdout


def test_teardown_refuses_when_the_stack_survives_removal(tmp_path: Path) -> None:
    client, state = _fake_runtime(tmp_path, containers=("core",))

    # A client that still reports the container after removing it stands in for
    # a runtime whose data root the golden restore cannot reach. Reporting that
    # as a clean reset is what would let residue survive into the next walk.
    result = _run(_teardown_lines(client), state=state, keeps_containers=True)

    assert "TEARDOWN_FAILED" in result.stdout, result.stdout + result.stderr


def test_the_bundle_directory_and_its_secrets_are_asserted_absent() -> None:
    # The bundle holds the server's owner-only secrets/ and is written into the
    # home, so the restore has to have taken it away with everything else.
    assert SELF_HOST_COMPOSE_PROJECT in YOKE_ABSENT_RELATIVE_DIRECTORIES


def test_the_teardown_runs_before_the_clear_replaces_the_runtime_data() -> None:
    ordered = FULL_RESET_SCRIPT
    teardown = ordered.index('run_reset_step "$reset_phase_stop_self_host_stack"')
    clear = ordered.index('run_reset_step "$reset_phase_clear_home"')
    # Ordering is the whole design: the daemon can only name its own objects
    # while it is up, and the clear can only replace its data once it is down.
    assert teardown < clear
    assert "stop_self_host_stack" in RESET_PHASES


def test_unrestored_detail_parses_a_bounded_sanitized_summary() -> None:
    assert unrestored_detail("YOKE_RESET_UNRESTORED_2 Library Application_Support") == {
        "unrestored_entry_count": 2,
        "unrestored_entries": ["Library", "Application_Support"],
    }
    assert unrestored_detail("YOKE_RESET_UNRESTORED_0") == {
        "unrestored_entry_count": 0,
        "unrestored_entries": [],
    }
    # A name that escaped sanitizing would reopen the closed output contract.
    assert unrestored_detail("YOKE_RESET_UNRESTORED_1 has;semicolon") is None
    assert unrestored_detail("YOKE_RESET_UNRESTORED_x name") is None
