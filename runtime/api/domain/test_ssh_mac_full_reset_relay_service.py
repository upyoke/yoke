"""Executed-program coverage for the Test Mac relay-service unload phase.

Every case drives a fake launchctl. A test never reaches the operator's real
launchd domain, which is the same boundary the local relay lifecycle keeps.
"""

from __future__ import annotations

from pathlib import Path

from runtime.api.domain.ssh_mac_full_reset_test_support import (
    assignment as _assignment,
    function_program as _function_program,
    require_zsh as _require_zsh,
    run_functions as _run_functions,
)
from yoke_harness.ssh_mac_full_reset_contract import (
    RELAY_SERVICE_LABEL,
    RELAY_SERVICE_LABEL_PREFIX,
    RESET_RELAY_SERVICE_KIND_UNLOAD_FAILED,
    RESET_RELAY_SERVICE_PREFIX,
)


#: The residue this phase exists for: launchd still names the job, and its PID
#: column is empty because no process is currently running for it.
_LOADED_WITHOUT_PID = "-\t78\t"


def _fake_launchctl(tmp_path: Path, *, refuse_bootout: bool = False) -> Path:
    """Write a launchctl double whose loaded set lives in a state file."""
    state = tmp_path / "loaded-labels"
    binary = tmp_path / "fake-launchctl"
    removes = (
        ""
        if refuse_bootout
        else """
    /usr/bin/grep -v -x -- "$label" "$state" > "$state.next" || true
    /bin/mv -- "$state.next" "$state"
"""
    )
    binary.write_text(
        f"""#!/bin/sh
state={state!s}
case "$1" in
  list)
    printf 'PID\\tStatus\\tLabel\\n'
    [ -f "$state" ] || exit 0
    while IFS= read -r label; do
      [ -n "$label" ] || continue
      printf -- '{_LOADED_WITHOUT_PID}%s\\n' "$label"
    done < "$state"
    ;;
  bootout)
    label="${{2##*/}}"
    [ -f "$state" ] || exit 0
{removes or "    exit 3"}
    ;;
esac
"""
    )
    binary.chmod(0o700)
    return binary


def _phase_lines(binary: Path, **overrides: str) -> tuple[str, ...]:
    """Run the unload phase against a fake launchctl and report its outcome."""
    return (
        _function_program(),
        _assignment("launchctl_path", str(binary)),
        # A one-second budget keeps a refused bootout from spending the
        # program's real wait; the loop shape under test is unchanged.
        "relay_unload_timeout=1",
        *(_assignment(name, value) for name, value in overrides.items()),
        'unload_relay_service || print -r -- "UNLOAD_REFUSED $failure_detail"',
        'print -r -- "UNLOADED $relay_unloaded_count"',
    )


def _loaded(binary: Path, *labels: str) -> None:
    (binary.parent / "loaded-labels").write_text(
        "".join(f"{label}\n" for label in labels)
    )


def test_unload_removes_a_relay_service_loaded_without_a_running_process(
    tmp_path: Path,
) -> None:
    _require_zsh()
    binary = _fake_launchctl(tmp_path)
    label = f"{RELAY_SERVICE_LABEL_PREFIX}57976ddac4709032"
    _loaded(binary, label)

    result = _run_functions(
        _phase_lines(binary),
        shell_home=tmp_path / "shell-home",
    )

    # A job with no PID is still a job: launchd restarts it, and it rewrites
    # the state directory the clear is about to remove.
    assert "UNLOAD_REFUSED" not in result.stdout, result.stdout + result.stderr
    assert "UNLOADED 1" in result.stdout
    assert (tmp_path / "loaded-labels").read_text() == ""


def test_unload_passes_when_the_account_has_no_relay_service_loaded(
    tmp_path: Path,
) -> None:
    _require_zsh()
    binary = _fake_launchctl(tmp_path)
    _loaded(binary)

    result = _run_functions(
        _phase_lines(binary),
        shell_home=tmp_path / "shell-home",
    )

    assert "UNLOAD_REFUSED" not in result.stdout, result.stdout + result.stderr
    assert "UNLOADED 0" in result.stdout


def test_unload_leaves_every_service_this_reset_does_not_own(
    tmp_path: Path,
) -> None:
    _require_zsh()
    binary = _fake_launchctl(tmp_path)
    _loaded(binary, "com.vendor.updater", "com.apple.something")

    result = _run_functions(
        _phase_lines(binary),
        shell_home=tmp_path / "shell-home",
    )

    assert "UNLOADED 0" in result.stdout, result.stdout + result.stderr
    # Service handling is limited to this account's Yoke relay; a bootout of
    # anything else would be this reset reaching outside its own residue.
    assert (tmp_path / "loaded-labels").read_text().splitlines() == [
        "com.vendor.updater",
        "com.apple.something",
    ]


def test_unload_covers_the_canonical_label_as_well_as_an_instance(
    tmp_path: Path,
) -> None:
    _require_zsh()
    binary = _fake_launchctl(tmp_path)
    _loaded(binary, RELAY_SERVICE_LABEL, "com.vendor.updater")

    result = _run_functions(
        _phase_lines(binary),
        shell_home=tmp_path / "shell-home",
    )

    # The golden home carries zero Yoke, so a relay under either name is
    # residue that recreates state the verifier requires absent.
    assert "UNLOADED 1" in result.stdout, result.stdout + result.stderr
    assert (tmp_path / "loaded-labels").read_text().splitlines() == [
        "com.vendor.updater",
    ]


def test_unload_stops_and_names_the_service_it_could_not_remove(
    tmp_path: Path,
) -> None:
    _require_zsh()
    binary = _fake_launchctl(tmp_path, refuse_bootout=True)
    label = f"{RELAY_SERVICE_LABEL_PREFIX}57976ddac4709032"
    _loaded(binary, label)

    result = _run_functions(
        _phase_lines(binary),
        shell_home=tmp_path / "shell-home",
    )

    # The refusal is the point: the phase runs before the reap and the clear,
    # so stopping here leaves the home intact instead of emptying it under a
    # service that would write it back.
    assert "UNLOAD_REFUSED" in result.stdout, result.stdout + result.stderr
    assert RESET_RELAY_SERVICE_PREFIX in result.stdout
    assert RESET_RELAY_SERVICE_KIND_UNLOAD_FAILED in result.stdout
    assert label in result.stdout
    assert (tmp_path / "loaded-labels").read_text().splitlines() == [label]


def test_unload_treats_an_unreachable_launchctl_as_nothing_loaded(
    tmp_path: Path,
) -> None:
    _require_zsh()

    result = _run_functions(
        _phase_lines(tmp_path / "absent-launchctl"),
        shell_home=tmp_path / "shell-home",
    )

    assert "UNLOAD_REFUSED" not in result.stdout, result.stdout + result.stderr
    assert "UNLOADED 0" in result.stdout
