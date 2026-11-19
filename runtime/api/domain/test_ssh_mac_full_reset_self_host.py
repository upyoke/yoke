"""Self-host teardown coverage for the dedicated Test Machine reset."""

from __future__ import annotations

import pytest

from pathlib import Path
from runtime.api.domain.ssh_mac_full_reset_self_host_test_support import (
    fake_runtime as _fake_runtime,
    run as _run,
    self_host_lines as _self_host_lines,
    teardown_lines as _teardown_lines,
)
from yoke_contracts.ssh_mac_full_reset_contract import (
    RESET_PHASES,
    YOKE_ABSENT_RELATIVE_DIRECTORIES,
)
from yoke_contracts.ssh_mac_full_reset_self_host_contract import (
    COMPOSE_PROJECT_LABEL,
    SELF_HOST_COMPOSE_PROJECT,
    RESET_SELF_HOST_KIND_DOCKER_UNREACHABLE,
    RESET_SELF_HOST_STATE_PREFIX,
)
from yoke_harness.ssh_mac_full_reset_receipt import unrestored_detail
from yoke_harness.ssh_mac_full_reset_script import FULL_RESET_SCRIPT


@pytest.mark.macos_only(reason="executes a macOS reset or capture program in /bin/zsh")
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


@pytest.mark.macos_only(reason="executes a macOS reset or capture program in /bin/zsh")
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


@pytest.mark.macos_only(reason="executes a macOS reset or capture program in /bin/zsh")
def test_teardown_is_a_clean_pass_on_a_host_with_no_container_runtime(
    tmp_path: Path,
) -> None:
    absent = tmp_path / "no-runtime-here"

    result = _run(_teardown_lines(absent), state=tmp_path)

    # A host that never ran a container has nothing to remove, which is a pass
    # rather than a skip: the end state the phase exists to reach is already met.
    assert "TEARDOWN_FAILED" not in result.stdout, result.stdout + result.stderr
    assert "REMOVED 0 0 0" in result.stdout
    assert "REACHABLE 0" in result.stdout


@pytest.mark.macos_only(reason="executes a macOS reset or capture program in /bin/zsh")
def test_teardown_refuses_naming_the_client_when_its_daemon_cannot_list(
    tmp_path: Path,
) -> None:
    client, state = _fake_runtime(tmp_path, containers=("core",))

    result = _run(_teardown_lines(client), state=state, daemon_down=True)

    # An unlistable daemon returns the same empty lists as an empty one, so a
    # pass here would report a clean host the reset never saw.
    assert "TEARDOWN_FAILED" in result.stdout, result.stdout + result.stderr
    assert "REACHABLE 0" in result.stdout
    assert (
        f"DETAIL {RESET_SELF_HOST_STATE_PREFIX}"
        f"{RESET_SELF_HOST_KIND_DOCKER_UNREACHABLE} {client}"
    ) in result.stdout
    assert "Cannot connect to the Docker daemon" in result.stderr
    assert not (state / "removed-containers").exists()


@pytest.mark.macos_only(reason="executes a macOS reset or capture program in /bin/zsh")
def test_teardown_reports_a_reachable_empty_daemon(tmp_path: Path) -> None:
    client, state = _fake_runtime(tmp_path, containers=())

    result = _run(_teardown_lines(client), state=state)

    assert "TEARDOWN_FAILED" not in result.stdout, result.stdout + result.stderr
    assert "REMOVED 0 0 0" in result.stdout
    assert "REACHABLE 1" in result.stdout


@pytest.mark.macos_only(reason="executes a macOS reset or capture program in /bin/zsh")
@pytest.mark.parametrize(("stopped", "passes"), [("0", False), ("1", True)])
def test_verify_excuses_only_a_daemon_this_reset_quit(
    tmp_path: Path, stopped: str, passes: bool
) -> None:
    client, state = _fake_runtime(tmp_path, containers=())
    lines = (
        *_self_host_lines(client, anchor="no-such-application"),
        f"self_host_runtime_stopped={stopped}",
        "self_host_stack_is_absent || print -r -- VERIFY_FAILED",
        'print -r -- "DETAIL $failure_detail"',
    )

    result = _run(lines, state=state, daemon_down=True)

    # The stop phase lists the stack empty before it quits the application, so
    # only that quit explains a silent daemon at verify; anything else refuses.
    assert ("VERIFY_FAILED" not in result.stdout) is passes, result.stdout
    if not passes:
        assert RESET_SELF_HOST_KIND_DOCKER_UNREACHABLE in result.stdout


@pytest.mark.macos_only(reason="executes a macOS reset or capture program in /bin/zsh")
def test_teardown_refuses_when_the_stack_survives_removal(tmp_path: Path) -> None:
    client, state = _fake_runtime(tmp_path, containers=("core",))

    # A client that still reports the container after removing it stands in for
    # a runtime whose data root the golden restore cannot reach. Reporting that
    # as a clean reset is what would let residue survive into the next walk.
    result = _run(_teardown_lines(client), state=state, keeps_containers=True)

    assert "TEARDOWN_FAILED" in result.stdout, result.stdout + result.stderr


def test_the_bundle_directory_and_its_secrets_are_asserted_absent() -> None:
    # The default bundle and its owner-only secrets live inside .yoke, so
    # asserting that machine directory absent also covers the server bundle.
    assert ".yoke" in YOKE_ABSENT_RELATIVE_DIRECTORIES
    assert SELF_HOST_COMPOSE_PROJECT == "yoke-server"


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
        "entry_errors": [],
    }
    assert unrestored_detail("YOKE_RESET_UNRESTORED_0") == {
        "unrestored_entry_count": 0,
        "unrestored_entries": [],
        "entry_errors": [],
    }
    # A name that escaped sanitizing would reopen the closed output contract.
    assert unrestored_detail("YOKE_RESET_UNRESTORED_1 has;semicolon") is None
    assert unrestored_detail("YOKE_RESET_UNRESTORED_x name") is None
