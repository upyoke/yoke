"""Restore-failure evidence and simulator quiescing in the Test Machine reset."""

from __future__ import annotations

from pathlib import Path
import shlex
import subprocess
import sys

from runtime.api.domain.ssh_mac_full_reset_test_support import (
    assignment,
    function_program,
    require_zsh,
    run_functions,
)
from yoke_harness.ssh_mac_full_reset_contract import (
    RESET_FAILURE_PREFIX,
    RESET_PHASES,
    RESET_RESTORE_ERROR_PREFIX,
    RESET_RESTORE_UNRESTORED_PREFIX,
    RESTORE_ERROR_EXCERPT_CHAR_CAP,
    SIMULATOR_DEVICE_SET_SUFFIX,
)
from yoke_harness.ssh_mac_full_reset_receipt import (
    failure_outcome,
    unrestored_detail,
)


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def test_a_stopped_restore_carries_each_entrys_copier_error(tmp_path: Path) -> None:
    require_zsh()
    golden = tmp_path / "golden-home"
    home = tmp_path / "live-home"
    _write(golden / "Library" / "Developer" / "CoreSimulator" / "state", "x\n")
    _write(golden / "Documents" / "notes.txt", "notes\n")
    (home / "Library").mkdir(parents=True)
    error_log = tmp_path / "restore-errors.log"
    locked = shlex.quote(str(home / "Library"))
    lines = (
        function_program(),
        assignment("home", str(home)),
        assignment("golden", str(golden)),
        assignment("restore_error_log", str(error_log)),
        assignment("restore_failure_report", str(error_log) + ".entries"),
        f"/bin/chmod 500 {locked}",
        "restore_golden || {",
        '  print -r -- "$failure_detail"',
        '  print -r -- "$failure_excerpts"',
        "}",
        f"/bin/chmod 700 {locked}",
    )

    result = run_functions(lines, shell_home=tmp_path / "shell-home")

    stdout = RESET_FAILURE_PREFIX + RESET_PHASES["restore_golden"] + "\n"
    stdout += result.stdout
    parsed = failure_outcome(stdout)
    assert parsed is not None, result.stdout + result.stderr
    _phase, _recovery_failed, detail = parsed
    restore_state = unrestored_detail(detail or "")
    assert restore_state is not None
    assert restore_state["unrestored_entries"] == ["Developer"]
    [error] = restore_state["entry_errors"]
    assert error["entry"] == "Developer"
    # The cause itself, not a pointer to a scratch log the exit removes.
    assert "Permission denied" in error["error_excerpt"]


def test_unrestored_detail_refuses_an_excerpt_outside_the_closed_contract() -> None:
    summary = RESET_RESTORE_UNRESTORED_PREFIX + "1 Developer"
    oversized = "x" * (RESTORE_ERROR_EXCERPT_CHAR_CAP + 1)
    assert (
        unrestored_detail(f"{summary}\n{RESET_RESTORE_ERROR_PREFIX}A {oversized}")
        is None
    )
    assert unrestored_detail(f"{summary}\nstray line") is None
    assert (
        unrestored_detail(f"{summary}\n{RESET_RESTORE_ERROR_PREFIX}a;b cp: denied")
        is None
    )


def test_only_an_unrestored_detail_may_span_several_lines() -> None:
    marker = RESET_FAILURE_PREFIX + RESET_PHASES["reap_processes"]
    assert failure_outcome(f"{marker}\n0 0 1.0\nextra") is None


def test_a_booted_simulator_device_in_the_home_is_a_reap_candidate(
    tmp_path: Path,
) -> None:
    require_zsh()
    home = tmp_path / "live-home"
    device_data = home / SIMULATOR_DEVICE_SET_SUFFIX / "DEVICE" / "data"
    device_data.mkdir(parents=True)
    # The stand-in for launchd_sim: a process naming the device's data
    # directory on its command line, which is how the real one is launched.
    device = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)", str(device_data)]
    )
    try:
        result = run_functions(
            (
                function_program(),
                assignment("home", str(home)),
                assignment("reap_user", subprocess.getoutput("id -un")),
                assignment("yoke_state_dir", str(home / ".yoke")),
                assignment(
                    "simulator_device_set_dir",
                    str(home / SIMULATOR_DEVICE_SET_SUFFIX),
                ),
                "reap_candidate_pids",
            ),
            shell_home=tmp_path / "shell-home",
        )
    finally:
        device.kill()
        device.wait()

    assert str(device.pid) in result.stdout.split(), result.stdout + result.stderr
